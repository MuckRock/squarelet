#!/bin/bash
# Check for overlapping Django migration numbers between the current branch and target branch
# This prevents migration conflicts when merging PRs

set -e

# Get the base branch from GitHub Actions context, default to master
BASE_BRANCH="${GITHUB_BASE_REF:-master}"

echo "Checking for migration conflicts against $BASE_BRANCH..."

# Fetch the base branch if we don't have it
git fetch origin "$BASE_BRANCH" --depth=1 2>/dev/null || true

# Find all Django app directories with migrations
MIGRATION_DIRS=$(find . -type d -name "migrations" -path "*/squarelet/*" | grep -v __pycache__ | grep -v ".venv" | grep -v "lib/")

conflicts_found=0

for migration_dir in $MIGRATION_DIRS; do
    app_name=$(basename "$(dirname "$migration_dir")")

    # Get migration files unique to current branch (not in base branch)
    current_migrations=$(git diff --name-only --diff-filter=A "origin/$BASE_BRANCH"...HEAD -- "$migration_dir" 2>/dev/null | grep -E '^.*/[0-9]{4}_.*\.py$' || true)

    # Get migration files unique to base branch (not in current branch)
    base_migrations=$(git diff --name-only --diff-filter=A HEAD..."origin/$BASE_BRANCH" -- "$migration_dir" 2>/dev/null | grep -E '^.*/[0-9]{4}_.*\.py$' || true)

    if [ -z "$current_migrations" ] || [ -z "$base_migrations" ]; then
        continue
    fi

    # Extract migration numbers from current branch
    current_numbers=$(echo "$current_migrations" | xargs -n1 basename 2>/dev/null | grep -oE '^[0-9]{4}' | sort -u || true)

    # Extract migration numbers from base branch
    base_numbers=$(echo "$base_migrations" | xargs -n1 basename 2>/dev/null | grep -oE '^[0-9]{4}' | sort -u || true)

    # Find overlapping numbers
    overlapping=$(comm -12 <(echo "$current_numbers") <(echo "$base_numbers") 2>/dev/null || true)

    if [ -n "$overlapping" ]; then
        echo ""
        echo "ERROR: Migration number conflict detected in $app_name app!"
        echo "The following migration numbers exist in both branches:"
        echo "$overlapping" | while read -r num; do
            echo "  - $num"
            echo "    In current branch:"
            echo "$current_migrations" | grep "^.*/${num}_" | sed 's/^/      /'
            echo "    In $BASE_BRANCH:"
            echo "$base_migrations" | grep "^.*/${num}_" | sed 's/^/      /'
        done
        echo ""
        echo "Please renumber your migration to avoid conflicts."
        conflicts_found=1
    fi
done

if [ $conflicts_found -eq 1 ]; then
    echo ""
    echo "Migration conflicts found! Please resolve before merging."
    exit 1
else
    echo "No migration conflicts detected."
    exit 0
fi
