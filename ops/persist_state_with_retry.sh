#!/usr/bin/env bash
set -euo pipefail

state_file="${1:-site_state.json}"
max_attempts="${STATE_PUSH_MAX_ATTEMPTS:-5}"

if git diff --quiet -- "$state_file"; then
  echo "No state changes"
  exit 0
fi

git add "$state_file"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git commit -m "chore: update fortress bot state"

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  echo "Persisting state: attempt ${attempt}/${max_attempts}"

  # Sync before every push so a transient GitHub error can recover on the
  # same workflow run instead of producing a false monitoring failure.
  if git fetch origin master && git rebase origin/master && git push origin HEAD:master; then
    echo "State persisted successfully"
    exit 0
  else
    rc=$?
  fi

  git rebase --abort >/dev/null 2>&1 || true

  if (( attempt == max_attempts )); then
    echo "State persistence failed after ${max_attempts} attempts" >&2
    exit "$rc"
  fi

  case "$attempt" in
    1) delay=2 ;;
    2) delay=5 ;;
    3) delay=10 ;;
    *) delay=20 ;;
  esac
  echo "State persistence attempt failed; retrying in ${delay}s" >&2
  sleep "$delay"
done
