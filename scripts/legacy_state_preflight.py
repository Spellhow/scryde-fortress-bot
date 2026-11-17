#!/usr/bin/env python3
"""Read-only legacy state migration inventory. No raw state or sensitive output."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from community.legacy_preflight import analyze_legacy_state


def main(argv=None):
    parser=argparse.ArgumentParser(description="Inspect legacy BSOE migration blockers without modifying files")
    parser.add_argument("--source",type=Path,default=Path("site_state.json"))
    parser.add_argument("--fail-on-blockers",action="store_true")
    args=parser.parse_args(argv)
    try:
        if args.source.stat().st_size > 10_000_000:
            raise ValueError("state file exceeds preflight size limit")
        data=json.loads(args.source.read_text(encoding="utf8"))
        report=analyze_legacy_state(data)
    except (ValueError,OSError,TypeError) as exc:
        # Never print raw data, paths, URLs, owner names or exception content.
        print("Legacy preflight failed safely ({})".format(type(exc).__name__),file=sys.stderr)
        return 2
    print(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2))
    return 1 if args.fail_on_blockers and report["blockers"] else 0


if __name__=="__main__":
    sys.exit(main())
