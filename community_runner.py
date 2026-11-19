#!/usr/bin/env python3
"""Opt-in GitHub-only runner for public community feeds and outbound webhooks."""
import argparse
import os
import sys
from pathlib import Path

from community.config import credential_environment, load_config
from community.runner import run
from community.state import DeliveryState


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lineage 2 community feed runner")
    parser.add_argument("--validate", action="store_true", help="validate config without network")
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
    state_path = Path(os.environ.get("COMMUNITY_STATE_FILE", "community_deliveries.json"))
    dry_run = os.environ.get("COMMUNITY_DRY_RUN", "false").lower() == "true"
    state_changed = False
    try:
        state = DeliveryState.load(state_path)
        credentials = credential_environment()
        summary = run(config, state, credentials=credentials, dry_run=dry_run)
        if not dry_run:
            state_changed = state.save(state_path)
    except Exception as exc:
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
