#!/usr/bin/env python3
"""Prepare an additional isolated Telegram/Discord target for GitHub-only Bot.

Uses existing trusted config, writes a separate candidate JSON and never
reads/writes credentials, Telegram messages, or existing community.json.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from community.config import load_config, parse_config

NEWS_TYPES = ("news", "event", "patch_note", "announcement")
CASTLE_TYPES = ("castle_owner_change", "siege_registration")


def add_destination(document, *, source_id, alias, kind, address_env,
                    token_env="", language="uk", event_types=(), clans=()):
    """Return fresh validated config JSON with a dedicated subscription."""
    config = parse_config(document)
    source = next((entry for entry in config.sources if entry.id == source_id), None)
    if source is None:
        raise ValueError("selected source does not exist")
    if any(target.id.casefold() == alias.casefold()
           for target in config.destinations.values()):
        raise ValueError("destination alias already exists")
    if kind not in {"telegram", "discord"}:
        raise ValueError("unknown destination type")
    if kind == "discord" and token_env:
        raise ValueError("Discord webhooks do not use bot token environment")
    if kind == "telegram" and not token_env:
        raise ValueError("Telegram destination requires a token env variable")
    is_castle = source.kind == "l2dex_castles"
    allowed = set(CASTLE_TYPES if is_castle else NEWS_TYPES)
    selected = tuple(event_types) if event_types else tuple(sorted(allowed))
    if not selected or any(item not in allowed for item in selected):
        raise ValueError("selected events unsupported by this source")
    if clans and not is_castle:
        # Other adapters currently emit Event.clan=None. Don't create an
        # apparently configured subscription that silently matches nothing.
        raise ValueError("news feed has no verified clan field")
    updated = deepcopy(document)
    destination = {"id":alias,"kind":kind,"address_env":address_env}
    if kind == "telegram":
        destination["token_env"] = token_env
    updated["destinations"].append(destination)
    updated["subscriptions"].append({
        "destination_id": alias,
        "world": {
            "network":source.world.network,
            "name":source.world.name,
            "chronicle":source.world.chronicle,
        },
        "source_ids":[source.id],
        "event_types":list(selected),
        "clans":list(clans),
        "language":language,
    })
    # The full parser catches malformed aliases, env names, overlapping
    # subscriptions and invalid languages; no special-case validator here.
    parse_config(updated)
    return updated


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Prepare a second GitHub-only Telegram or Discord destination"
    )
    parser.add_argument("--config",type=Path,default=Path("community.json"))
    parser.add_argument("--source-id",required=True)
    parser.add_argument("--alias",required=True)
    parser.add_argument("--kind",choices=("telegram","discord"),required=True)
    parser.add_argument("--address-env",required=True)
    parser.add_argument("--token-env",default="")
    parser.add_argument("--language",default="uk")
    parser.add_argument("--event-types",default="")
    parser.add_argument("--clans",default="")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.config.stat().st_size > 1_000_000:
            raise ValueError("community config exceeds size limit")
        document=json.loads(args.config.read_text(encoding="utf8"))
        if not isinstance(document,dict):
            raise ValueError("config must be a JSON object")
        updated=add_destination(
            document,
            source_id=args.source_id,alias=args.alias,kind=args.kind,
            address_env=args.address_env,
            token_env=args.token_env or ("TG_TOKEN" if args.kind=="telegram" else ""),
            language=args.language,
            event_types=tuple(s.strip() for s in args.event_types.split(",") if s.strip()),
            clans=tuple(s.strip() for s in args.clans.split(",") if s.strip()),
        )
        if args.output.resolve()==args.config.resolve():
            raise ValueError("cannot overwrite the current config")
        if not args.output.parent.is_dir():
            raise ValueError("output directory must exist")
        with args.output.open("x",encoding="utf8") as output:
            json.dump(updated,output,ensure_ascii=False,sort_keys=True,indent=2)
            output.write("\n")
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"Destination setup refused ({type(exc).__name__}); no existing config modified",
              file=sys.stderr)
        return 2
    print("Candidate config created. Review it, add the referenced GitHub Secret(s), "
          "then promote the candidate to community.json. No live message sent.")
    return 0


if __name__=="__main__":
    sys.exit(main())
