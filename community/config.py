"""Versioned public configuration. Private addresses/tokens come from env only."""
from dataclasses import dataclass
from datetime import datetime
import json
import os
import re
from urllib.parse import urlsplit, parse_qsl
from .models import World, Destination, Subscription, required
from .schedules import ScheduledEvent, MAX_SCHEDULES

SOURCE_KINDS = {"rss", "telegram_public", "json_api", "webpage", "l2dex_castles"}
MAX_SOURCES = 30
MAX_DESTINATIONS = 30


@dataclass(frozen=True)
class SourceConfig:
    id: str
    kind: str
    world: World
    url: str
    selector: str = ""
    enabled: bool = True

    def __post_init__(self):
        required(self.id, "source id")
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"unsupported source kind {self.kind!r}")
        parts = urlsplit(self.url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
            raise ValueError("source must be a public HTTPS URL without credentials or fragment")
        if parts.port not in (None, 443):
            raise ValueError("custom source ports are unsupported")
        # This URL is committed to GitHub. Reject obvious query-string secrets.
        # Public filters such as ?format=rss remain supported.
        sensitive = {"token", "key", "api_key", "apikey", "access_token", "secret",
                     "password", "pass", "signature", "authorization", "auth"}
        if any(name.casefold() in sensitive for name, _ in parse_qsl(parts.query, keep_blank_values=True)):
            raise ValueError("source URL query must not contain credentials")
        if self.kind == "telegram_public" and not re.fullmatch(r"/s/[A-Za-z0-9_]{4,}", parts.path):
            raise ValueError("telegram public source requires https://t.me/s/<channel>")
        if self.kind == "telegram_public" and parts.hostname not in {"t.me", "telegram.me"}:
            raise ValueError("Telegram source host must be t.me or telegram.me")
        if self.kind == "l2dex_castles":
            if parts.hostname not in {"lineage2dex.com", "www.lineage2dex.com"}:
                raise ValueError("L2Dex castle source must use the official domain")
            if not re.fullmatch(r"/(?:en|ru)/rating/[a-z0-9-]+\.\d+", parts.path) or parts.query:
                raise ValueError("L2Dex castle source must point to a game world's ranking page")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be true or false")
        if not isinstance(self.selector, str) or len(self.selector) > 120:
            raise ValueError("CSS selector must be text of at most 120 characters")


@dataclass(frozen=True)
class CommunityConfig:
    sources: tuple
    destinations: dict
    subscriptions: tuple
    schedules: tuple = ()
    version: int = 1


def _strset(value):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("filters must be arrays of strings")
    return frozenset(value)


def _world(item):
    if not isinstance(item, dict):
        raise ValueError("world must be an object")
    return World(item.get("network"), item.get("name"), item.get("chronicle", ""))


def parse_config(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("unsupported community config version")
    src = data.get("sources", [])
    dest = data.get("destinations", [])
    subs = data.get("subscriptions", [])
    scheduled = data.get("scheduled_events", [])
    if not all(isinstance(value, list) for value in (src, dest, subs, scheduled)):
        raise ValueError("sources, destinations, subscriptions and scheduled_events must be arrays")
    if len(src) > MAX_SOURCES or len(dest) > MAX_DESTINATIONS or len(scheduled) > MAX_SCHEDULES:
        raise ValueError("too many sources, destinations, or scheduled events")
    sources = []
    for item in src:
        if not isinstance(item, dict):
            raise ValueError("source entry must be an object")
        sources.append(SourceConfig(
            id=item.get("id"), kind=item.get("kind"), world=_world(item.get("world")),
            url=item.get("url", ""), selector=item.get("selector", ""),
            enabled=item.get("enabled", True),
        ))
    destinations = {}
    for item in dest:
        if not isinstance(item, dict):
            raise ValueError("destination entry must be an object")
        target = Destination(
            id=item.get("id"), kind=item.get("kind"),
            address_env=item.get("address_env", ""),
            token_env=item.get("token_env", ""),
        )
        if target.id in destinations:
            raise ValueError("duplicate destination ID")
        destinations[target.id] = target
    subscriptions = []
    for item in subs:
        if not isinstance(item, dict):
            raise ValueError("subscription entry must be an object")
        subscription = Subscription(
            destination_id=item.get("destination_id"),
            world=_world(item.get("world")),
            event_types=_strset(item.get("event_types", [])),
            source_ids=_strset(item.get("source_ids", [])),
            clans=_strset(item.get("clans", [])),
            language=item.get("language", "uk"),
        )
        if subscription.destination_id not in destinations:
            raise ValueError("subscription references missing destination")
        subscriptions.append(subscription)
    schedules = []
    for item in scheduled:
        if not isinstance(item, dict):
            raise ValueError("scheduled event entry must be an object")
        start_text = item.get("starts_at")
        if not isinstance(start_text, str):
            raise ValueError("scheduled event starts_at must be an ISO date with offset")
        try:
            starts_at = datetime.fromisoformat(start_text)
        except ValueError as exc:
            raise ValueError("invalid scheduled event start time") from exc
        times = item.get("remind_before_minutes", [60])
        if not isinstance(times, list):
            raise ValueError("remind_before_minutes must be an array")
        schedules.append(ScheduledEvent(
            identifier=item.get("id"),
            world=_world(item.get("world")),
            title=item.get("title"),
            body=item.get("body", ""),
            starts_at=starts_at,
            remind_before_minutes=tuple(times),
            clan=item.get("clan"),
            enabled=item.get("enabled", True),
        ))
    schedule_ids = [(entry.world.identity, entry.identifier) for entry in schedules]
    if len(schedule_ids) != len(set(schedule_ids)):
        raise ValueError("duplicate scheduled event ID within a world")
    ids = [source.id for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source ID")
    allowed_worlds = {source.world.identity for source in sources} | {entry.world.identity for entry in schedules}
    if any(sub.world.identity not in allowed_worlds for sub in subscriptions):
        raise ValueError("subscription world has no configured source")
    known_sources = set(ids)
    if schedules:
        known_sources.add("manual_schedule")
    if any(sub.source_ids - known_sources for sub in subscriptions):
        raise ValueError("subscription references unknown source")
    return CommunityConfig(tuple(sources), destinations, tuple(subscriptions), tuple(schedules))


def load_config(path):
    from pathlib import Path
    return parse_config(json.loads(Path(path).read_text(encoding="utf-8")))


def credential_environment(environ=None):
    """Combine ordinary injected secrets with optional JSON secret map.

    Never include the resulting mapping in logs or persisted state.
    """
    env = dict(os.environ if environ is None else environ)
    text = env.get("COMMUNITY_SECRETS_JSON", "")
    if text:
        extra = json.loads(text)
        if not isinstance(extra, dict) or any(
            not isinstance(k, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", k)
            or not isinstance(v, str) for k, v in extra.items()
        ):
            raise ValueError("COMMUNITY_SECRETS_JSON must be a flat map of env names to secrets")
        env.update(extra)
    return env
