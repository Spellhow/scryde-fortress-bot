#!/usr/bin/env python3
"""Inspect a few configured public sources. No secrets, no sends, no state."""
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.config import load_config
from community.preview import preview_sources


def main():
    try:
        config = load_config(Path(os.environ.get("COMMUNITY_CONFIG_FILE", "community.json")))
        result = preview_sources(
            config, selected=os.environ.get("PREVIEW_SOURCE_ID", "").strip(),
        )
    except Exception as exc:
        print(f"Public source preview failed safely ({type(exc).__name__})")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if any("error" in item for item in result["results"]) else 0


if __name__ == "__main__":
    sys.exit(main())
