#!/bin/bash
# Post the screenshots a visual run changed as a before/after comment on the
# pull request, or mark an earlier comment resolved once the run passes.
#
# A comment cannot carry uploaded images, so they are pushed to an orphan
# branch and embedded from there.

set -euo pipefail

: "${PR_NUMBER:?}" "${OUTCOME:?}" "${BASE_REF:?}" "${HEAD_SHA:?}"

BRANCH=visual-snapshots
MARKER="<!-- visual-snapshots -->"
RUN_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"

existing=$(gh api "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" --paginate \
  --jq ".[] | select(.body | startswith(\"$MARKER\")) | .id" | tail -n 1)

post() {
  if [ -n "$existing" ]; then
    gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$existing" -F body=@"$1" >/dev/null
  else
    gh pr comment "$PR_NUMBER" --body-file "$1"
  fi
}

body="$RUNNER_TEMP/visual-comment.md"

if [ "$OUTCOME" = success ]; then
  [ -n "$existing" ] || exit 0
  printf '%s\n### Visual changes\n\nNone against `%s` as of %s.\n' \
    "$MARKER" "$BASE_REF" "$HEAD_SHA" >"$body"
  post "$body"
  exit 0
fi

# Playwright leaves <name>-actual.png beside each failed screenshot, and
# <name>-expected.png too unless the page is new.
actuals=$(find test-results -name '*-actual.png' 2>/dev/null | sort)
if [ -z "$actuals" ]; then
  echo "The run failed without changing a screenshot; nothing to post."
  exit 0
fi

tree="$RUNNER_TEMP/$BRANCH"
if git fetch --depth=1 origin "$BRANCH"; then
  git worktree add --detach "$tree" FETCH_HEAD
else
  git worktree add --orphan -b "$BRANCH" "$tree"
fi

dest="pr-$PR_NUMBER/$GITHUB_RUN_ID"
rows=""
while read -r actual; do
  dir=$(dirname "$actual")
  name=$(basename "$actual" -actual.png)
  # Test result folders end in the project name.
  case "$dir" in
  *-visual-phone) project=visual-phone ;;
  *) project=visual ;;
  esac
  mkdir -p "$tree/$dest/$project"
  cp "$actual" "$tree/$dest/$project/$name-after.png"
  if [ -f "$dir/$name-expected.png" ]; then
    cp "$dir/$name-expected.png" "$tree/$dest/$project/$name-before.png"
    cp "$dir/$name-diff.png" "$tree/$dest/$project/$name-diff.png"
  fi
  rows+="$project $name"$'\n'
done <<<"$actuals"

git -C "$tree" add "$dest"
git -C "$tree" -c user.name="github-actions[bot]" \
  -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
  commit -qm "Visual changes for #$PR_NUMBER"
# Other pull requests push here too, always to their own folder.
for attempt in 1 2 3; do
  git -C "$tree" push -q origin "HEAD:refs/heads/$BRANCH" && break
  [ "$attempt" -lt 3 ] || exit 1
  git -C "$tree" pull -q --rebase origin "$BRANCH"
done
raw="https://raw.githubusercontent.com/$GITHUB_REPOSITORY/$(git -C "$tree" rev-parse HEAD)/$dest"

img() {
  if [ -f "$tree/$dest/$1" ]; then
    printf '<a href="%s/%s"><img src="%s/%s" width="400"></a>' "$raw" "$1" "$raw" "$1"
  else
    printf '_new page_'
  fi
}

{
  printf '%s\n### Visual changes\n\n' "$MARKER"
  printf 'Screenshots that differ from `%s` as of %s: %d. ' "$BASE_REF" "$HEAD_SHA" "$(wc -l <<<"$actuals")"
  printf 'The full report is in the `visual-report` artifact of [this run](%s).\n\n' "$RUN_URL"
  while read -r project name; do
    [ -n "$name" ] || continue
    diff=""
    if [ -f "$tree/$dest/$project/$name-diff.png" ]; then
      diff=$(printf ' · <a href="%s/%s/%s-diff.png">View diff</a>' "$raw" "$project" "$name")
    fi
    printf '<details><summary><code>%s / %s</code>%s</summary>\n\n' "$project" "$name" "$diff"
    printf '| Before | After |\n| --- | --- |\n'
    printf '| %s | %s |\n\n</details>\n\n' \
      "$(img "$project/$name-before.png")" "$(img "$project/$name-after.png")"
  done <<<"$rows"
} >"$body"
post "$body"
