"""Read-only Scryde ranking adapter for shadow comparisons.

The existing github_runner.py remains the authoritative live publisher.
Never infer lost ownership from missing/invalid rows.
"""
from datetime import datetime, timezone

from community.models import Event, Provenance
from .scryde_rows import valid_scryde_ranking_rows, get_attackers


class ScrydeRankingAdapter:
    def __init__(self, source_id, page_url, object_type="fortress"):
        if object_type not in ("fortress", "castle"):
            raise ValueError("invalid object type")
        self.source_id = source_id
        self.page_url = page_url
        self.object_type = object_type

    def parse(self, payload, *, world):
        if not isinstance(payload, list):
            raise ValueError("ranking must contain a list")
        now = datetime.now(timezone.utc)
        events = []
        trusted_rows, _ = valid_scryde_ranking_rows(payload)
        for row in trusted_rows:
            owner = row.get("owner")
            name = row.get("name")
            object_id = row.get("id")
            # An explicitly observed owner=None means NPC / unowned.
            # The same shared row validator rejects a missing or malformed
            # owner field, so we never invent an owner for an incomplete row.
            if owner is not None and not isinstance(owner, dict):
                continue
            if not name or object_id is None:
                continue
            owner_name = owner["name"] if owner is not None else "NPC (unowned)"
            names = sorted({name.strip() for name in get_attackers(row)})
            siege_at = row.get("siege_at")
            if not names or not isinstance(siege_at, (int, float)) or siege_at <= now.timestamp():
                continue
            try:
                occurrence = datetime.fromtimestamp(siege_at, tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                continue
            events.append(Event(
                world=world, source_id=self.source_id,
                external_id=f"{self.object_type}:{object_id}:{int(siege_at)}",
                kind="siege_registration",
                title=f"{name}: attackers registered",
                body=f"Owner: {owner_name}; attackers: {', '.join(names)}",
                source_url=self.page_url, provenance=Provenance.OBSERVED,
                observed_at=now, occurs_at=occurrence,
                clan=owner["name"] if owner is not None else None,
                object_name=str(name), revision="|".join(names),
            ))
        return events
