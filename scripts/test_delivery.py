#!/usr/bin/env python3
"""One-time opt-in test; never prints destination IDs, tokens or webhook URLs."""
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.config import credential_environment, load_config
from community.delivery_probe import probe_destination


def main():
    if os.environ.get("DELIVERY_TEST_CONFIRM") != "yes":
        print("No message sent: explicit test confirmation required")
        return 2
    alias = os.environ.get("DELIVERY_TEST_DESTINATION", "")
    try:
        config = load_config(Path(os.environ.get("COMMUNITY_CONFIG_FILE", "community.json")))
        creds = credential_environment()
        ok = probe_destination(config, alias, creds)
    except Exception as exc:
        # Exceptions from request libraries can include private webhook URLs.
        print(f"Delivery test failed safely ({type(exc).__name__})")
        return 1
    if not ok:
        print("Delivery not confirmed; verify bot permissions and repository secrets")
        return 1
    print("Delivery confirmed: one manual diagnostic message was created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
