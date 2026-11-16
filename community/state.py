"""Versioned public state without chat IDs, tokens, or private messages."""
from dataclasses import dataclass, field
from pathlib import Path
import json
import os
import tempfile
from .models import digest

SCHEMA_VERSION = 1
MAX_DELIVERIES = 10000


def delivery_key(destination_id, event_id):
    return digest((destination_id.casefold(), event_id))


@dataclass
class DeliveryState:
    delivered: dict = field(default_factory=dict)
    cursors: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("state must be an object")
        if data.get("schema_version", 1) != SCHEMA_VERSION:
            raise ValueError("unknown state schema version; migration required")
        deliveries, cursors = data.get("delivered", {}), data.get("cursors", {})
        if not isinstance(deliveries, dict) or any(type(v) is not int for v in deliveries.values()):
            raise ValueError("invalid delivery entries")
        if not isinstance(cursors, dict) or any(not isinstance(v, str) for v in cursors.values()):
            raise ValueError("invalid source cursor entries")
        return cls(dict(deliveries), dict(cursors))

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else cls()

    def was_delivered(self, destination_id, event_id):
        return delivery_key(destination_id, event_id) in self.delivered

    def mark_delivered(self, destination_id, event_id, at_unix):
        self.delivered[delivery_key(destination_id, event_id)] = int(at_unix)
        if len(self.delivered) > MAX_DELIVERIES:
            self.delivered = dict(sorted(self.delivered.items(), key=lambda pair: pair[1])[-MAX_DELIVERIES:])

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".l2state-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({"schema_version": SCHEMA_VERSION, "delivered": self.delivered,
                           "cursors": self.cursors}, output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
