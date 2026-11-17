#!/usr/bin/env bash
# Only GitHub-only Community Bot state. Never use for legacy BSOE site_state.
set -euo pipefail
state_file=community_deliveries.json
max_attempts="${STATE_PUSH_MAX_ATTEMPTS:-5}"
case "$max_attempts" in 1|2|3|4|5) ;; *) echo "Invalid retry limit" >&2; exit 2 ;; esac
if [[ ! -f "$state_file" ]]; then echo "No community state to persist"; exit 0; fi
if git ls-files --error-unmatch -- "$state_file" >/dev/null 2>&1 &&
   git diff --quiet -- "$state_file"; then
  echo "No community state changes"
  exit 0
fi
if [[ -n "$(git diff --cached --name-only)" ]]; then
  echo "Unrelated staged changes; refusing state persistence" >&2
  exit 1
fi
base_ref="$(git rev-parse HEAD)"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
empty='{"schema_version":1,"delivered":{},"cursors":{}}'
if git cat-file -e "${base_ref}:${state_file}" 2>/dev/null; then
  git show "${base_ref}:${state_file}" > "$work/base.json"
else printf '%s\n' "$empty" > "$work/base.json"; fi
cp -- "$state_file" "$work/ours.json"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for ((attempt=1; attempt<=max_attempts; attempt++)); do
  echo "Community state persistence attempt $attempt/$max_attempts"
  if git fetch origin master; then
    remote="$(git rev-parse origin/master)"
    if git cat-file -e "${remote}:${state_file}" 2>/dev/null; then
      git show "${remote}:${state_file}" > "$work/theirs.json"
    else printf '%s\n' "$empty" > "$work/theirs.json"; fi
    if ! python3 scripts/merge_community_state.py \
        --base "$work/base.json" --ours "$work/ours.json" \
        --theirs "$work/theirs.json" --output "$work/merged.json"; then
      echo "Ambiguous state change: nothing pushed" >&2
      exit 1
    fi
    # Mixed reset keeps worktree, stages only our merged JSON; NEVER --hard.
    git reset --mixed "$remote" >/dev/null
    cp -- "$work/merged.json" "$state_file"
    git add -- "$state_file"
    if git diff --cached --quiet -- "$state_file"; then
      echo "Community state already persisted"
      exit 0
    fi
    git commit -m "chore: update community delivery state"
    if git push origin HEAD:master; then
      echo "Community state persisted safely"
      exit 0
    fi
    echo "Remote advanced during push; retrying" >&2
  fi
  if (( attempt == max_attempts )); then
    echo "Community state not persisted; refusing to discard receipts" >&2
    exit 1
  fi
  case "$attempt" in 1) sleep 2 ;; 2) sleep 5 ;; 3) sleep 10 ;; *) sleep 20 ;; esac
done
