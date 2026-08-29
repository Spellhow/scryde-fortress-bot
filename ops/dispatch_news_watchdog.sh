#!/usr/bin/env bash
set -euo pipefail

export GH_CONFIG_DIR="${GH_CONFIG_DIR:-/opt/sentinelx-cloud-core/.config/gh}"
REPO="${SCRYDE_REPO:-Spellhow/scryde-fortress-bot}"
WORKFLOW="${SCRYDE_NEWS_WORKFLOW:-news-bot.yml}"
REF="${SCRYDE_REF:-master}"

active_count="$({
  gh run list \
    --repo "$REPO" \
    --workflow "$WORKFLOW" \
    --limit 20 \
    --json status \
    --jq '[.[] | select(.status == "queued" or .status == "in_progress" or .status == "waiting" or .status == "requested" or .status == "pending")] | length'
} 2>/dev/null)"

if [[ "${active_count:-0}" != "0" ]]; then
  echo "News Bot already active (${active_count}); skipping dispatch"
  exit 0
fi

echo "Dispatching $WORKFLOW on $REPO@$REF"
gh workflow run "$WORKFLOW" --repo "$REPO" --ref "$REF"
