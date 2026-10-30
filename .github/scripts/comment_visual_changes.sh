#!/bin/bash
# Post the screenshots a visual run changed as a before/after comment on the
# pull request and leave the head commit's status pending, or mark it passed
# and any earlier comment resolved once nothing differs. Exits 1 if a test
# failed for any reason but a changed screenshot.
#
# A comment cannot carry uploaded images, so they are uploaded to S3 and
# embedded from there. The bucket deletes them after 30 days.

set -euo pipefail

: "${PR_NUMBER:?}" "${OUTCOME:?}" "${BASE_REF:?}" "${HEAD_SHA:?}"

BUCKET=muckrock-workflow-outputs
MARKER="<!-- visual-snapshots -->"
RUN_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"

existing=$(gh api "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" --paginate \
  --jq ".[] | select(.body | startswith(\"$MARKER\")) | .id" | tail -n 1)

# Prints the comment's URL.
post() {
  if [ -n "$existing" ]; then
    gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$existing" -F body=@"$1" --jq .html_url
  else
    gh api "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" -F body=@"$1" --jq .html_url
  fi
}

status() {
  gh api "repos/$GITHUB_REPOSITORY/statuses/$HEAD_SHA" -f context="Visual changes" \
    -f state="$1" -f description="$2" -f target_url="$3" >/dev/null
}

body="$RUNNER_TEMP/visual-comment.md"

if [ "$OUTCOME" = success ]; then
  status success "No changes against $BASE_REF" "$RUN_URL"
  [ -n "$existing" ] || exit 0
  printf '%s\n### Visual changes\n\nNone against `%s` as of %s.\n' \
    "$MARKER" "$BASE_REF" "$HEAD_SHA" >"$body"
  post "$body" >/dev/null
  exit 0
fi

broken=0
jq -e '[.errors[], (.. | .results? // empty | .[].errors[])]
  | all(.message // "" | contains("toHaveScreenshot"))' \
  test-results/results.json >/dev/null || broken=1

# Playwright leaves <name>-actual.png beside each failed screenshot, and
# <name>-expected.png too unless the page is new.
actuals=$(find test-results -name '*-actual.png' | sort)
if [ -z "$actuals" ]; then
  echo "The run failed without changing a screenshot."
  exit 1
fi

stage="$RUNNER_TEMP/visual-changes"
# GitHub's image proxy caches by URL, so a re-run must not reuse the last
# attempt's paths.
prefix="runs/visual-regression-checks/$GITHUB_RUN_ID/$GITHUB_RUN_ATTEMPT"
rows=""
while read -r actual; do
  dir=$(dirname "$actual")
  name=$(basename "$actual" -actual.png)
  # Test result folders end in the project name.
  case "$dir" in
  *-visual-phone) project=visual-phone ;;
  *) project=visual ;;
  esac
  mkdir -p "$stage/$project"
  cp "$actual" "$stage/$project/$name-after.png"
  if [ -f "$dir/$name-expected.png" ]; then
    cp "$dir/$name-expected.png" "$stage/$project/$name-before.png"
    cp "$dir/$name-diff.png" "$stage/$project/$name-diff.png"
  fi
  rows+="$project $name"$'\n'
done <<<"$actuals"

aws s3 sync "$stage" "s3://$BUCKET/$prefix/" --only-show-errors
url="https://$BUCKET.s3.amazonaws.com/$prefix"

img() {
  if [ -f "$stage/$1" ]; then
    printf '<a href="%s/%s"><img src="%s/%s" width="400"></a>' "$url" "$1" "$url" "$1"
  else
    printf '_new page_'
  fi
}

count=$(wc -l <<<"$actuals")
{
  printf '%s\n### Visual changes\n\n' "$MARKER"
  printf 'Screenshots that differ from `%s` as of %s: %d. ' "$BASE_REF" "$HEAD_SHA" "$count"
  printf 'The full report is in the `visual-report` artifact of [this run](%s).\n\n' "$RUN_URL"
  while read -r project name; do
    [ -n "$name" ] || continue
    diff=""
    if [ -f "$stage/$project/$name-diff.png" ]; then
      diff=$(printf ' · <a href="%s/%s/%s-diff.png">View diff</a>' "$url" "$project" "$name")
    fi
    printf '<details><summary><code>%s / %s</code>%s</summary>\n\n' "$project" "$name" "$diff"
    printf '| Before | After |\n| --- | --- |\n'
    printf '| %s | %s |\n\n</details>\n\n' \
      "$(img "$project/$name-before.png")" "$(img "$project/$name-after.png")"
  done <<<"$rows"
} >"$body"
comment=$(post "$body")
status pending "Screenshots that differ from $BASE_REF: $count" "$comment"

if [ "$broken" = 1 ]; then
  echo "A test failed for a reason other than a changed screenshot."
  exit 1
fi
