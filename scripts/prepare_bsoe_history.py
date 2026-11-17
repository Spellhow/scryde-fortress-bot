#!/usr/bin/env python3
"""Dry-run first; create one separate combined public source-state candidate.

This is NOT a cutover or moderator-state import. It never contacts Telegram
or GitHub and never overwrites the old/current state files.
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.config import load_config
from community.legacy_cutover import prepare_bsoe_history_checkpoints
from community.state import DeliveryState


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare both BSOE public news checkpoint hashes")
    parser.add_argument("--legacy", type=Path, default=Path("site_state.json"))
    parser.add_argument("--config", type=Path, default=Path("community.json"))
    parser.add_argument("--current", type=Path, default=Path("community_deliveries.json"))
    parser.add_argument("--telegram-source", required=True)
    parser.add_argument("--forum-source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)

    if bool(args.output) != bool(args.confirm):
        print("Combined BSOE checkpoint refused: output and confirmation must be paired",
              file=sys.stderr)
        return 2

    try:
        for path in (args.legacy, args.config, args.current):
            if path.exists() and path.stat().st_size > 10_000_000:
                raise ValueError("state or configuration exceeds size limit")
        old = json.loads(args.legacy.read_text(encoding="utf8"))
        config = load_config(args.config)
        current = DeliveryState.load(args.current)
        candidate = prepare_bsoe_history_checkpoints(
            old, config,
            telegram_source=args.telegram_source,
            forum_source=args.forum_source,
            destination=args.destination,
            current=current,
        )
        result = {
            "format": "bsoe-combined-public-history-v1",
            "public_sources_validated": 2,
            "existing_delivery_receipts_preserved": len(current.delivered),
            "new_checkpoint_markers": sum(
                name not in current.cursors for name in candidate.cursors
            ),
            "cutover_authorized": False,
            "output_written": False,
        }
        if args.output:
            if args.output.resolve() in {
                args.legacy.resolve(), args.config.resolve(), args.current.resolve()
            }:
                raise ValueError("cannot overwrite input state")
            with args.output.open("x", encoding="utf8") as output:
                json.dump({
                    "schema_version": 1,
                    "delivered": candidate.delivered,
                    "cursors": candidate.cursors,
                }, output, indent=2, sort_keys=True, ensure_ascii=False)
                output.write("\n")
            result["output_written"] = True
        print(json.dumps(result, sort_keys=True, indent=2))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("Combined BSOE checkpoint refused ({})".format(type(exc).__name__),
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
