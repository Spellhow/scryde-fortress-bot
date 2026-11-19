#!/usr/bin/env python3
"""Generate a safe starter community.json for a fresh GitHub template copy.

Never fetches game data, reads bot credentials, or overwrites an existing file.
Users set GitHub Actions secrets and opt-in schedule variables separately.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

# Available both from root CLI and from a GitHub Actions checkout.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.config import SOURCE_KINDS, parse_config


def build_document(*, network, world, chronicle, source_kind, source_url,
                   destination_kind, destination_alias="clan-channel",
                   language="uk", clan="", include_keywords=""):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,40}", destination_alias):
        raise ValueError("destination alias must be 3-41 lowercase characters")
    if source_kind not in SOURCE_KINDS:
        raise ValueError("unsupported source type")
    if destination_kind == "telegram":
        destination = {
            "id": destination_alias, "kind": "telegram",
            "address_env": "TG_CHAT", "token_env": "TG_TOKEN",
        }
    elif destination_kind == "discord":
        destination = {
            "id": destination_alias, "kind": "discord",
            "address_env": "DISCORD_WEBHOOK",
        }
    else:
        raise ValueError("destination must be telegram or discord")
    if not isinstance(include_keywords, str):
        raise ValueError("include_keywords must be text")
    keywords = [word.strip() for word in include_keywords.split(",") if word.strip()]
    # The public Scryde Telegram channel covers multiple worlds. A one-world
    # setup therefore defaults to a conservative world-name gate.
    if source_kind in {"telegram_public", "scryde_forum"} and not keywords:
        # These official public sources mix updates for different game worlds.
        # An unfiltered default is unsafe; require a conservative world gate.
        keywords = [world.strip()]
    if source_kind == "l2dex_castles" and keywords:
        raise ValueError("L2Dex castle snapshots cannot use news keyword filters")
    world_spec = {"network": network, "name": world, "chronicle": chronicle}
    event_types = (
        ["castle_owner_change", "siege_registration"]
        if source_kind == "l2dex_castles"
        else ["news", "patch_note", "announcement", "event"]
    )
    data = {
        "version": 1,
        "sources": [{
            "id": "initial-source",
            "kind": source_kind,
            "world": world_spec,
            "url": source_url,
            "enabled": True,
            "include_keywords": keywords if source_kind != "l2dex_castles" else [],
        }],
        "destinations": [destination],
        "subscriptions": [{
            "destination_id": destination_alias, "world": world_spec,
            "source_ids": ["initial-source"],
            "event_types": event_types,
            "clans": [clan.strip()] if clan and clan.strip() else [],
            "language": language,
        }],
        "scheduled_events": [],
    }
    parse_config(data)
    return data


def write_document(data, path):
    target = Path(path)
    if target.exists():
        raise FileExistsError("Community config already exists; setup never overwrites it")
    if not target.parent.exists():
        raise ValueError("output directory does not exist")
    # Exclusive create protects existing community files from a concurrent setup.
    with target.open("x", encoding="utf-8") as output:
        json.dump(data, output, indent=2, ensure_ascii=False)
        output.write("\n")


def main(argv=None):
    env = os.environ
    parser = argparse.ArgumentParser(description="Create a GitHub-only Lineage II community bot config")
    parser.add_argument("--network", default=env.get("SETUP_NETWORK"), required=not bool(env.get("SETUP_NETWORK")))
    parser.add_argument("--world", default=env.get("SETUP_WORLD"), required=not bool(env.get("SETUP_WORLD")))
    parser.add_argument("--chronicle", default=env.get("SETUP_CHRONICLE", ""))
    parser.add_argument("--source-kind", default=env.get("SETUP_SOURCE_KIND", "l2dex_castles"), choices=sorted(SOURCE_KINDS))
    parser.add_argument("--source-url", default=env.get("SETUP_SOURCE_URL"), required=not bool(env.get("SETUP_SOURCE_URL")))
    parser.add_argument("--destination-kind", default=env.get("SETUP_DESTINATION_KIND", "telegram"), choices=("telegram", "discord"))
    parser.add_argument("--destination-alias", default=env.get("SETUP_DESTINATION_ALIAS", "clan-channel"))
    parser.add_argument("--language", default=env.get("SETUP_LANGUAGE", "uk"))
    parser.add_argument("--clan", default=env.get("SETUP_CLAN", ""))
    parser.add_argument("--include-keywords", default=env.get("SETUP_INCLUDE_KEYWORDS", ""),
                        help="comma-separated terms required in title/body for public news feeds")
    parser.add_argument("--output", default="community.json")
    args = parser.parse_args(argv)
    try:
        document = build_document(
            network=args.network, world=args.world, chronicle=args.chronicle,
            source_kind=args.source_kind, source_url=args.source_url,
            destination_kind=args.destination_kind, destination_alias=args.destination_alias,
            language=args.language, clan=args.clan, include_keywords=args.include_keywords,
        )
        write_document(document, args.output)
    except (ValueError, FileExistsError, OSError) as exc:
        # Safe, bounded messages; do not echo raw URL or secret values.
        print(f"Setup refused ({type(exc).__name__}). Check source URL, inputs and output path.", file=sys.stderr)
        return 2
    print("Created community.json. Add repository secrets and set opt-in variables before running Community Bot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
