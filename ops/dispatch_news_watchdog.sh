#!/usr/bin/env bash
set -euo pipefail

export GH_CONFIG_DIR="${GH_CONFIG_DIR:-/opt/sentinelx-cloud-core/.config/gh}"
REPO="${SCRYDE_REPO:-Spellhow/scryde-fortress-bot}"
REF="${SCRYDE_REF:-master}"
GH_RETRIES="${SCRYDE_GH_RETRIES:-3}"

list_active_runs() {
  local workflow="$1"
  local attempt output rc

  for ((attempt = 1; attempt <= GH_RETRIES; attempt++)); do
    if output="$(gh run list \
      --repo "$REPO" \
      --workflow "$workflow" \
      --limit 20 \
      --json status \
      --jq '[.[] | select(.status == "queued" or .status == "in_progress" or .status == "waiting" or .status == "requested" or .status == "pending")] | length' 2>&1)"; then
      printf '%s' "$output"
      return 0
    else
      rc=$?
    fi

    echo "WARN: gh run list failed for $workflow (attempt $attempt/$GH_RETRIES, rc=$rc): $output" >&2
    if (( attempt < GH_RETRIES )); then
      sleep $((attempt * 2))
    fi
  done

  return "${rc:-1}"
}

dispatch_once() {
  local workflow="$1"
  local output rc

  if output="$(gh workflow run "$workflow" --repo "$REPO" --ref "$REF" 2>&1)"; then
    [[ -n "$output" ]] && echo "$output"
    return 0
  else
    rc=$?
  fi

  echo "WARN: gh workflow run failed for $workflow (rc=$rc): $output" >&2
  return "$rc"
}

dispatch_workflow() {
  local workflow="$1"
  local active_count attempt

  if ! active_count="$(list_active_runs "$workflow")"; then
    echo "ERROR: unable to query active GitHub Actions runs for $workflow after $GH_RETRIES attempts" >&2
    return 1
  fi

  if [[ "${active_count:-0}" != "0" ]]; then
    echo "$workflow already active (${active_count}); skipping dispatch"
    return 0
  fi

  for ((attempt = 1; attempt <= GH_RETRIES; attempt++)); do
    echo "Dispatching $workflow on $REPO@$REF (attempt $attempt/$GH_RETRIES)"
    if dispatch_once "$workflow"; then
      return 0
    fi

    # A failed HTTP response can be ambiguous: GitHub may have accepted the
    # dispatch even if the client did not receive the response. Re-check before
    # retrying so a transient network error does not create duplicate runs.
    if active_count="$(list_active_runs "$workflow")" && [[ "${active_count:-0}" != "0" ]]; then
      echo "$workflow became active after the dispatch error; treating it as dispatched"
      return 0
    fi

    if (( attempt < GH_RETRIES )); then
      sleep $((attempt * 2))
    fi
  done

  echo "ERROR: failed to dispatch $workflow after $GH_RETRIES attempts" >&2
  return 1
}

status=0
if [[ -n "${SCRYDE_WORKFLOW:-}" ]]; then
  dispatch_workflow "$SCRYDE_WORKFLOW" || status=1
else
  # Keep the two workflows independent: a transient failure in one must not
  # prevent the other from being checked/dispatched.
  dispatch_workflow "siege-bot.yml" || status=1
  dispatch_workflow "news-bot.yml" || status=1
fi

exit "$status"
