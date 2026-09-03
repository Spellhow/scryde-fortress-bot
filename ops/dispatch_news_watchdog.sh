#!/usr/bin/env bash
set -euo pipefail

export GH_CONFIG_DIR="${GH_CONFIG_DIR:-/opt/sentinelx-cloud-core/.config/gh}"
REPO="${SCRYDE_REPO:-Spellhow/scryde-fortress-bot}"
REF="${SCRYDE_REF:-master}"

dispatch_workflow() {
  local workflow="$1"
  local active_count

  active_count="$({
    gh run list \
      --repo "$REPO" \
      --workflow "$workflow" \
      --limit 20 \
      --json status \
      --jq '[.[] | select(.status == "queued" or .status == "in_progress" or .status == "waiting" or .status == "requested" or .status == "pending")] | length'
  } 2>/dev/null)"

  if [[ "${active_count:-0}" != "0" ]]; then
    echo "$workflow already active (${active_count}); skipping dispatch"
    return 0
  fi

  echo "Dispatching $workflow on $REPO@$REF"
  gh workflow run "$workflow" --repo "$REPO" --ref "$REF"
}

if [[ -n "${SCRYDE_WORKFLOW:-}" ]]; then
  dispatch_workflow "$SCRYDE_WORKFLOW"
else
  # Siege first: fortress/castle alerts are the most latency-sensitive checks.
  dispatch_workflow "siege-bot.yml"
  dispatch_workflow "news-bot.yml"
fi
