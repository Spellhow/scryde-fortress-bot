#!/usr/bin/env python3
"""Opt-in, conservative public Telegram source checkpoint bridge.

Dry-run by default. The explicit output is a NEW schema-v1 public-state
candidate, not a live cutover. Never writes legacy site_state.json or sends.
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.config import load_config
from community.legacy_telegram_bridge import prepare_public_telegram_watermark
from community.state import DeliveryState


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare BSOE public news watermark")
    parser.add_argument("--legacy", type=Path, default=Path("site_state.json"))
    parser.add_argument("--config", type=Path, default=Path("community.json"))
    parser.add_argument("--current", type=Path, default=Path("community_deliveries.json"))
    parser.add_argument("--source-alias", required=True)
    parser.add_argument("--destination-alias", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)

    if bool(args.output) != bool(args.confirm):
        print("Watermark preparation refused: --output and --confirm must be used together",
              file=sys.stderr)
        return 2
    try:
        if args.legacy.stat().st_size > 10_000_000:
            raise ValueError("legacy state size limit")
        if args.current.exists() and args.current.stat().st_size > 10_000_000:
            raise ValueError("current state size limit")
        original = json.loads(args.legacy.read_text(encoding="utf8"))
        config = load_config(args.config)
        state = DeliveryState.load(args.current)
        candidate = prepare_public_telegram_watermark(
            original, config, args.source_alias, args.destination_alias, state
        )
        # Legacy sections other than the validated public Telegram news
        # checkpoint are never imported, including forum/wiki moderation.
        forum = original.get("forum_news", {})
        if not isinstance(forum, dict) or not isinstance(forum.get("pending", []), list):
            raise ValueError("invalid unmapped legacy forum history")
        result = {
            "format": "bsoe-public-telegram-watermark-v1",
            "public_telegram_checkpoint_valid": True,
            "existing_delivery_receipts_preserved": len(candidate.delivered),
            "unmapped_legacy_forum_items": len(forum.get("pending", [])),
            "cutover_authorized": False,
            "output_written": False,
        }
        if args.output is not None:
            # Refuse overwrites even if the caller supplies the old state or
            # current delivery path; no secrets/PII ever enter the candidate.
            if args.output.resolve() in {
                args.legacy.resolve(), args.config.resolve(), args.current.resolve()
            }:
                raise ValueError("cannot overwrite source or current state files")
            payload = {
                "schema_version": 1,
                "delivered": candidate.delivered,
                "cursors": candidate.cursors,
            }
            # Exclusive create means a failed or repeated execution never
            # replaces an existing state file.
            with args.output.open("x", encoding="utf8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
            result["output_written"] = True
        print(json.dumps(result, sort_keys=True, indent=2))
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print("Watermark preparation refused ({})".format(type(exc).__name__),
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
