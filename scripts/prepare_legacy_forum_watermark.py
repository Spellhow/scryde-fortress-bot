#!/usr/bin/env python3
"""Dry-run-first, partial public Scryde forum history checkpoint.

No live BSOE cutover, Git commit, moderation, secret reads, or network calls.
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.config import load_config
from community.legacy_forum_bridge import prepare_public_forum_watermark
from community.state import DeliveryState


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare public BSOE forum watermark")
    parser.add_argument("--legacy", type=Path, default=Path("site_state.json"))
    parser.add_argument("--config", type=Path, default=Path("community.json"))
    parser.add_argument("--current", type=Path, default=Path("community_deliveries.json"))
    parser.add_argument("--source-alias", required=True)
    parser.add_argument("--destination-alias", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.output) != bool(args.confirm):
        print("Forum checkpoint refused: --output and --confirm are required together",
              file=sys.stderr)
        return 2
    try:
        if args.legacy.stat().st_size > 10_000_000:
            raise ValueError("oversized legacy state")
        if args.current.exists() and args.current.stat().st_size > 10_000_000:
            raise ValueError("oversized current state")
        old = json.loads(args.legacy.read_text(encoding="utf8"))
        config = load_config(args.config)
        current = DeliveryState.load(args.current)
        candidate = prepare_public_forum_watermark(
            old, config, args.source_alias, args.destination_alias, current
        )
        telegram = old.get("news", {})
        if not isinstance(telegram, dict) or not isinstance(telegram.get("pending", []), list):
            raise ValueError("invalid unmatched public Telegram queue metadata")
        report = {
            "format": "bsoe-public-forum-watermark-v1",
            "forum_checkpoint_valid": True,
            "existing_delivery_receipts_preserved": len(candidate.delivered),
            "unmapped_legacy_telegram_items": len(telegram.get("pending", [])),
            "cutover_authorized": False,
            "output_written": False,
        }
        if args.output is not None:
            if args.output.resolve() in {
                args.legacy.resolve(), args.config.resolve(), args.current.resolve()
            }:
                raise ValueError("cannot overwrite legacy or current input")
            payload = {
                "schema_version": 1,
                "delivered": candidate.delivered,
                "cursors": candidate.cursors,
            }
            with args.output.open("x", encoding="utf8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
            report["output_written"] = True
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print("Forum checkpoint refused ({})".format(type(exc).__name__),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
