#!/usr/bin/env python3
"""Opt-in GitHub-only runner for public community feeds and outbound webhooks."""
import argparse
import os
import sys
from pathlib import Path

from community.config import credential_environment, load_config
from community.runner import run
from community.state import DeliveryState
from community.credential_preflight import check_credentials


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lineage 2 community feed runner")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate", action="store_true", help="validate config without network")
    modes.add_argument("--check-credentials", action="store_true",
                       help="offline check of configured delivery secret references")
    args = parser.parse_args(argv)
    path = Path(os.environ.get("COMMUNITY_CONFIG_FILE", "community.json"))
    if not path.exists():
        print("Community config missing: create community.json from community.example.json")
        return 2
    try:
        config = load_config(path)
    except (ValueError, OSError, TypeError) as exc:
        print(f"Invalid community config: {type(exc).__name__}")
        return 2
    if args.validate:
        print(f"Config valid: {len(config.sources)} sources, {len(config.destinations)} destinations")
        return 0
    if args.check_credentials:
        try:
            active, issues = check_credentials(config, credential_environment())
        except (ValueError, TypeError, OSError) as exc:
            print(f"Credential preflight refused ({type(exc).__name__})")
            return 2
        print(f"Credential preflight: active_destinations={active}, issues={len(issues)}")
        for variable, reason in issues:
            # Only env-var *names* validated by Destination are displayed.
            # Tokens, chat IDs, and webhook URL values are never logged.
            print(f"warning: {variable}: {reason}")
        return 1 if issues else 0
    state_path = Path(os.environ.get("COMMUNITY_STATE_FILE", "community_deliveries.json"))
    dry_run = os.environ.get("COMMUNITY_DRY_RUN", "false").lower() == "true"
    state_changed = False
    try:
        state = DeliveryState.load(state_path)
        credentials = credential_environment()
        try:
            summary = run(config, state, credentials=credentials, dry_run=dry_run)
        finally:
            # run() may have already acknowledged some successful sends or
            # warmed a source before an unrelated later step raises. Retain
            # those receipts even on an unexpected exception; the workflow's
            # always-run Git persistence step can then commit partial progress.
            if not dry_run:
                state_changed = state.save(state_path)
    except Exception as exc:
        # Never log exception messages: transports can put tokens/URLs there.
        print(f"Community runner failed safely ({type(exc).__name__})")
        return 1
    print(
        f"Community {'DRY-RUN ' if dry_run else ''}completed: "
        f"sources={summary.sources_checked}, events={summary.events_seen}, "
        f"subscriptions_initialized={summary.subscriptions_initialized}, "
        f"attempted={summary.attempts}, sent={summary.sent}, "
        f"deferred_sources={summary.deferred_sources}, errors={len(summary.errors)}, "
        f"state_changed={'yes' if state_changed else 'no'}"
    )
    for error in summary.errors:
        print(f"warning: {error}")
    # Source errors do not abort other sources, but CI should surface degraded runs.
    return 1 if summary.errors else 0


if __name__ == "__main__":
    sys.exit(main())
