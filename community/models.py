"""Normalized game world, event, and destination contracts."""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
import re
from typing import FrozenSet, Optional


def required(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value.strip()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:32]


class Provenance(str, Enum):
    OBSERVED = "observed"
    SCHEDULED = "scheduled"
    MANUAL = "manual"


@dataclass(frozen=True)
class World:
    network: str
    name: str
    chronicle: str = ""

    def __post_init__(self):
        object.__setattr__(self, "network", required(self.network, "network"))
        object.__setattr__(self, "name", required(self.name, "world"))
        if not isinstance(self.chronicle, str):
            raise ValueError("chronicle must be text")

    @property
    def identity(self):
        return digest((self.network.casefold(), self.name.casefold(), self.chronicle.strip().casefold()))


@dataclass(frozen=True)
class Event:
    world: World
    source_id: str
    external_id: str
    kind: str
    title: str
    body: str
    source_url: str
    provenance: Provenance
    observed_at: datetime
    occurs_at: Optional[datetime] = None
    clan: Optional[str] = None
    object_name: Optional[str] = None
    revision: str = ""

    def __post_init__(self):
        if not isinstance(self.world, World) or not isinstance(self.provenance, Provenance):
            raise ValueError("world and provenance are required")
        for name in ("source_id", "external_id", "kind", "title", "source_url"):
            required(getattr(self, name), name)
        if not isinstance(self.body, str):
            raise ValueError("body must be text")
        for stamp in (self.observed_at, self.occurs_at):
            if stamp is not None and (not isinstance(stamp, datetime) or stamp.utcoffset() is None):
                raise ValueError("timestamps must include timezone")

    @property
    def event_id(self):
        return digest((self.world.identity, self.source_id.casefold(), self.external_id, self.kind))

    @property
    def fingerprint(self):
        return digest((self.title, self.body, self.revision, self.occurs_at.isoformat() if self.occurs_at else ""))


@dataclass(frozen=True)
class Destination:
    id: str  # human-readable alias, never the Telegram numeric chat ID
    kind: str
    address_env: str
    token_env: str = ""

    def __post_init__(self):
        required(self.id, "destination id")
        if self.kind not in {"telegram", "discord"}:
            raise ValueError("Unsupported destination kind")
        for var in (self.address_env, self.token_env):
            if var and not re.fullmatch(r"[A-Z][A-Z0-9_]*", var):
                raise ValueError("credentials must be referenced by env var name only")
        required(self.address_env, "address_env")


@dataclass(frozen=True)
class Subscription:
    destination_id: str
    world: World
    event_types: FrozenSet[str] = field(default_factory=frozenset)
    source_ids: FrozenSet[str] = field(default_factory=frozenset)
    clans: FrozenSet[str] = field(default_factory=frozenset)
    language: str = "uk"

    def __post_init__(self):
        required(self.destination_id, "destination_id")
        if not isinstance(self.world, World):
            raise ValueError("world is required")
        if not re.fullmatch(r"[a-z]{2}(-[a-zA-Z0-9]+)?", self.language):
            raise ValueError("invalid language code")

    def matches(self, event):
        return (
            event.world.identity == self.world.identity
            and (not self.event_types or event.kind in self.event_types)
            and (not self.source_ids or event.source_id in self.source_ids)
            and (not self.clans or (event.clan is not None and event.clan.casefold() in {c.casefold() for c in self.clans}))
        )
