#!/usr/bin/env bash
set -euo pipefail

export GH_CONFIG_DIR="${GH_CONFIG_DIR:-/opt/sentinelx-cloud-core/.config/gh}"
REPO="${SCRYDE_REPO:-Spellhow/scryde-fortress-bot}"
REF="${SCRYDE_REF:-master}"
GH_RETRIES="${SCRYDE_GH_RETRIES:-3}"
STALE_ACTIVE_MINUTES="${SCRYDE_STALE_ACTIVE_MINUTES:-20}"
STALE_SUCCESS_MINUTES="${SCRYDE_STALE_SUCCESS_MINUTES:-30}"
ALERT_COOLDOWN_SECONDS="${SCRYDE_ALERT_COOLDOWN_SECONDS:-21600}"
WATCHDOG_STATE_DIR="${SCRYDE_WATCHDOG_STATE_DIR:-/var/lib/scryde-fortress-watchdog}"
WATCHDOG_STATE_FILE="$WATCHDOG_STATE_DIR/state"

ALERT_TOKEN="${SCRYDE_TG_TOKEN:-${TG_TOKEN:-}}"
ALERT_CHAT="${SCRYDE_TG_CHAT:-${TG_CHAT_DEBUG:-${TG_CHAT:-}}}"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

get_runs_json() {
  local workflow="$1"
  local limit="${2:-20}"
  local attempt output rc

  for ((attempt = 1; attempt <= GH_RETRIES; attempt++)); do
    if output="$(gh run list \
      --repo "$REPO" \
      --workflow "$workflow" \
      --limit "$limit" \
      --json status,conclusion,createdAt,updatedAt,databaseId,url 2>&1)"; then
      if printf '%s' "$output" | jq -e 'type == "array"' >/dev/null 2>&1; then
        printf '%s' "$output"
        return 0
      fi
      rc=1
      output="invalid JSON from gh: $output"
    else
      rc=$?
    fi

    log "WARN: gh run list failed for $workflow (attempt $attempt/$GH_RETRIES, rc=$rc): $output" >&2
    if (( attempt < GH_RETRIES )); then
      sleep $((attempt * 2))
    fi
  done

  return "${rc:-1}"
}

list_fresh_active_runs() {
  local workflow="$1"
  local output cutoff fresh_count stale_rows

  output="$(get_runs_json "$workflow" 30)" || return 1
  cutoff="$(date -u -d "${STALE_ACTIVE_MINUTES} minutes ago" +%s)"

  fresh_count="$(printf '%s' "$output" | jq --argjson cutoff "$cutoff" '
    [.[]
      | select(.status == "queued" or .status == "in_progress" or .status == "waiting" or .status == "requested" or .status == "pending")
      | select((.createdAt | fromdateiso8601) >= $cutoff)
    ] | length
  ')"

  stale_rows="$(printf '%s' "$output" | jq -r --argjson cutoff "$cutoff" '
    .[]
    | select(.status == "queued" or .status == "in_progress" or .status == "waiting" or .status == "requested" or .status == "pending")
    | select((.createdAt | fromdateiso8601) < $cutoff)
    | "id=\(.databaseId) status=\(.status) created=\(.createdAt) url=\(.url)"
  ')"
  if [[ -n "$stale_rows" ]]; then
    while IFS= read -r row; do
      log "WARN: ignoring stale GitHub Actions run for $workflow: $row" >&2
    done <<< "$stale_rows"
  fi

  printf '%s' "$fresh_count"
}

dispatch_once() {
  local workflow="$1"
  local output rc

  if output="$(gh workflow run "$workflow" --repo "$REPO" --ref "$REF" 2>&1)"; then
    [[ -n "$output" ]] && log "$output"
    return 0
  else
    rc=$?
  fi

  log "WARN: gh workflow run failed for $workflow (rc=$rc): $output" >&2
  return "$rc"
}

dispatch_workflow() {
  local workflow="$1"
  local active_count attempt

  if ! active_count="$(list_fresh_active_runs "$workflow")"; then
    log "ERROR: unable to query active GitHub Actions runs for $workflow after $GH_RETRIES attempts" >&2
    return 1
  fi

  if [[ "${active_count:-0}" != "0" ]]; then
    log "$workflow already has a fresh active run (${active_count}); skipping dispatch"
    return 0
  fi

  for ((attempt = 1; attempt <= GH_RETRIES; attempt++)); do
    log "Dispatching $workflow on $REPO@$REF (attempt $attempt/$GH_RETRIES)"
    if dispatch_once "$workflow"; then
      return 0
    fi

    # A failed HTTP response can be ambiguous: GitHub may have accepted the
    # dispatch even if the client did not receive the response. Re-check before
    # retrying so a transient network error does not create duplicate runs.
    if active_count="$(list_fresh_active_runs "$workflow")" && [[ "${active_count:-0}" != "0" ]]; then
      log "$workflow became active after the dispatch error; treating it as dispatched"
      return 0
    fi

    if (( attempt < GH_RETRIES )); then
      sleep $((attempt * 2))
    fi
  done

  log "ERROR: failed to dispatch $workflow after $GH_RETRIES attempts" >&2
  return 1
}

latest_success_health() {
  local workflow="$1"
  local output latest updated_at updated_epoch now_epoch age_seconds max_age_seconds

  output="$(get_runs_json "$workflow" 100)" || {
    printf 'cannot query recent runs for %s' "$workflow"
    return 1
  }

  latest="$(printf '%s' "$output" | jq -c '[.[] | select(.status == "completed" and .conclusion == "success")] | sort_by(.updatedAt) | last // empty')"
  if [[ -z "$latest" ]]; then
    printf 'no successful run found for %s' "$workflow"
    return 1
  fi

  updated_at="$(printf '%s' "$latest" | jq -r '.updatedAt')"
  updated_epoch="$(date -u -d "$updated_at" +%s)"
  now_epoch="$(date -u +%s)"
  age_seconds=$((now_epoch - updated_epoch))
  max_age_seconds=$((STALE_SUCCESS_MINUTES * 60))

  if (( age_seconds > max_age_seconds )); then
    printf '%s last success is %dm old (limit %dm): %s' \
      "$workflow" "$((age_seconds / 60))" "$STALE_SUCCESS_MINUTES" "$(printf '%s' "$latest" | jq -r '.url')"
    return 1
  fi

  return 0
}

load_watchdog_state() {
  INCIDENT_ACTIVE=0
  LAST_ALERT_AT=0
  if [[ ! -f "$WATCHDOG_STATE_FILE" ]]; then
    return 0
  fi

  while IFS='=' read -r key value; do
    case "$key" in
      INCIDENT_ACTIVE) [[ "$value" =~ ^[01]$ ]] && INCIDENT_ACTIVE="$value" ;;
      LAST_ALERT_AT) [[ "$value" =~ ^[0-9]+$ ]] && LAST_ALERT_AT="$value" ;;
    esac
  done < "$WATCHDOG_STATE_FILE"
}

save_watchdog_state() {
  mkdir -p "$WATCHDOG_STATE_DIR"
  umask 077
  printf 'INCIDENT_ACTIVE=%s\nLAST_ALERT_AT=%s\n' "$INCIDENT_ACTIVE" "$LAST_ALERT_AT" > "$WATCHDOG_STATE_FILE"
}

send_alert() {
  local text="$1"

  if [[ -z "$ALERT_TOKEN" || -z "$ALERT_CHAT" ]]; then
    log "WARN: Telegram watchdog alert not configured; set SCRYDE_TG_TOKEN and SCRYDE_TG_CHAT in /etc/scryde-fortress-watchdog.env" >&2
    return 1
  fi

  if curl -fsS --retry 2 --retry-delay 2 --connect-timeout 5 --max-time 20 \
    --data-urlencode "chat_id=$ALERT_CHAT" \
    --data-urlencode "text=$text" \
    "https://api.telegram.org/bot${ALERT_TOKEN}/sendMessage" >/dev/null; then
    log "Telegram watchdog alert sent"
    return 0
  fi

  log "ERROR: failed to send Telegram watchdog alert" >&2
  return 1
}

notify_incident() {
  local problem="$1"
  local now_epoch
  now_epoch="$(date -u +%s)"

  if (( INCIDENT_ACTIVE == 0 || now_epoch - LAST_ALERT_AT >= ALERT_COOLDOWN_SECONDS )); then
    send_alert "🚨 Scryde Fortress Bot unhealthy\n\n${problem}\n\nVPS watchdog is still running and will retry automatically." || true
    LAST_ALERT_AT="$now_epoch"
  fi
  INCIDENT_ACTIVE=1
  save_watchdog_state
}

notify_recovery() {
  if (( INCIDENT_ACTIVE == 1 )); then
    send_alert "✅ Scryde Fortress Bot recovered. News Bot and Siege Bot have recent successful runs again." || true
  fi
  INCIDENT_ACTIVE=0
  LAST_ALERT_AT=0
  save_watchdog_state
}

main() {
  local status=0
  local problems=()
  local detail

  mkdir -p "$WATCHDOG_STATE_DIR"
  load_watchdog_state

  if [[ -n "${SCRYDE_WORKFLOW:-}" ]]; then
    if ! dispatch_workflow "$SCRYDE_WORKFLOW"; then
      problems+=("dispatch failed: $SCRYDE_WORKFLOW")
      status=1
    fi
  else
    # Keep the two workflows independent: a transient failure in one must not
    # prevent the other from being checked/dispatched.
    if ! dispatch_workflow "siege-bot.yml"; then
      problems+=("dispatch failed: Siege Bot")
      status=1
    fi
    if ! dispatch_workflow "news-bot.yml"; then
      problems+=("dispatch failed: News Bot")
      status=1
    fi
  fi

  if ! detail="$(latest_success_health "siege-bot.yml")"; then
    problems+=("$detail")
    status=1
  fi
  if ! detail="$(latest_success_health "news-bot.yml")"; then
    problems+=("$detail")
    status=1
  fi

  if (( status != 0 )); then
    local problem_text
    problem_text="$(printf '%s\n' "${problems[@]}")"
    log "ERROR: watchdog unhealthy: ${problem_text//$'\n'/; }" >&2
    notify_incident "$problem_text"
    return 1
  fi

  notify_recovery
  log "watchdog healthy"
  return 0
}

main "$@"
