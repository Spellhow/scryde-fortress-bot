#!/usr/bin/env python3
"""Read-only legacy moderation decisions for a state snapshot.

No imports from runtime (Playwright/Telegram/Gemini), API calls, file writes,
or raw news content in stdout or errors.
"""
import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.legacy_news_decisions import summarize_legacy_news_queue


def main(argv=None):
    parser = argparse.ArgumentParser(description="Privacy-safe read-only news queue replay")
    parser.add_argument("--state", type=Path, default=Path("site_state.json"))
    parser.add_argument("--now", type=int, default=None, help="Unix UTC timestamp for reproducible replay")
    parser.add_argument("--mode", choices=("prod", "debug"), default="prod")
    parser.add_argument("--expire-hours", type=int, default=24)
    parser.add_argument("--grace-minutes", type=int, default=30)
    args = parser.parse_args(argv)

    if not 0 <= args.expire_hours <= 168 or not 0 <= args.grace_minutes <= 1440:
        print("News replay refused (invalid bounds)", file=sys.stderr)
        return 2
    now = args.now if args.now is not None else int(time.time())
    if now < 0:
        print("News replay refused (invalid timestamp)", file=sys.stderr)
        return 2
    try:
        if args.state.stat().st_size > 10_000_000:
            raise ValueError("oversized state")
        loaded = json.loads(args.state.read_text(encoding="utf8"))
        report = summarize_legacy_news_queue(
            loaded,
            now=now,
            expire_hours=args.expire_hours,
            grace_minutes=args.grace_minutes,
            target_chat=args.mode,
        )
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        # Never include content, URLs, filenames, or token-bearing exceptions.
        print("News replay refused ({})".format(type(exc).__name__), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
