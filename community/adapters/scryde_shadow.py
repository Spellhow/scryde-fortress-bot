"""Read-only Scryde siege ranking diagnostics.

This is a shadow observer, not a notification engine. It never performs HTTP,
calls Gemini/Telegram, or modifies production state. It deliberately refuses
to infer loss from a missing or malformed row.
"""
from dataclasses import dataclass
from typing import Mapping

from .scryde_rows import is_valid_scryde_ranking_row, get_attackers


@dataclass(frozen=True)
class RankingObject:
    identifier: str
    name: str
    owner: str | None
    attackers: tuple[str, ...]
    siege_at: int
    # An explicit owner=None is a verifiable NPC/unowned row; an unknown owner
    # shape is rejected before it reaches this model.


@dataclass(frozen=True)
class ShadowReport:
    object_type: str
    observed_objects: int
    owned_by_clan: tuple[str, ...]
    attacks_by_clan: tuple[str, ...]
    confirmed_owner_changes: tuple[str, ...]
    missing_prior_owned: tuple[str, ...]
    rejected_rows: int
    duplicate_ids: int

    def summary(self) -> dict:
        """No clan/owner/player names or raw response content in diagnostics."""
        return {
            "object_type": self.object_type,
            "observed": self.observed_objects,
            "ours": len(self.owned_by_clan),
            "our_attacks": len(self.attacks_by_clan),
            "confirmed_owner_changes": len(self.confirmed_owner_changes),
            "missing_prior_owned_deferred": len(self.missing_prior_owned),
            "rejected": self.rejected_rows,
            "duplicate_ids": self.duplicate_ids,
        }


def _row(item) -> RankingObject | None:
    # Exactly the same trust boundary as the authoritative BSOE runner.
    if not is_valid_scryde_ranking_row(item):
        return None
    owner_obj = item["owner"]
    owner = owner_obj["name"].strip() if isinstance(owner_obj, dict) else None
    attackers = tuple(sorted({name.strip() for name in get_attackers(item)}))
    siege = item.get("siege_at") or 0
    # Shadow projections intentionally refuse out-of-range wall clock values.
    if siege > 4102444800:
        return None
    return RankingObject(
        str(item["id"]), item["name"].strip(), owner, attackers, int(siege)
    )


def _previously_owned(section: Mapping) -> set[str]:
    """Only objects with explicit had=true in legacy state count as owned."""
    previous = set()
    tracked = section.get("objects", {})
    if isinstance(tracked, dict):
        for identifier, status in tracked.items():
            if isinstance(status, dict) and status.get("had") is True:
                previous.add(str(identifier))
    # Legacy state may still keep a single previous object pre-migration.
    if section.get("had") is True and section.get("id") is not None:
        previous.add(str(section["id"]))
    return previous


def inspect_scryde_ranking(items, *, clan: str, object_type: str, previous_state: Mapping | None = None) -> ShadowReport:
    """Project ranking into read-only observations with fail-closed transitions.

    A row missing from a successful parse is not evidence of ownership loss.
    An explicit owner change on a present, valid row is only a candidate for a
    legacy loss notification, not an instruction to send anything.
    """
    if object_type not in {"fortress", "castle"}:
        raise ValueError("unsupported ranking object type")
    if not isinstance(clan, str) or not clan.strip():
        raise ValueError("clan must be non-empty")
    if not isinstance(items, list):
        raise ValueError("ranking snapshot must be a list")
    previous = _previously_owned(previous_state or {})
    rows = {}
    invalid = duplicates = 0
    poisoned = set()
    for item in items:
        parsed = _row(item)
        if parsed is None:
            invalid += 1
            continue
        if parsed.identifier in rows or parsed.identifier in poisoned:
            duplicates += 1
            poisoned.add(parsed.identifier)
            rows.pop(parsed.identifier, None)
            continue
        rows[parsed.identifier] = parsed
    owned = sorted(x.identifier for x in rows.values() if x.owner == clan)
    attacking = sorted(x.identifier for x in rows.values() if x.owner != clan and clan in x.attackers)
    loss_candidates = sorted(key for key in previous if key in rows and rows[key].owner != clan)
    missing = sorted(previous - rows.keys())
    return ShadowReport(
        object_type=object_type,
        observed_objects=len(rows),
        owned_by_clan=tuple(owned),
        attacks_by_clan=tuple(attacking),
        confirmed_owner_changes=tuple(loss_candidates),
        missing_prior_owned=tuple(missing),
        rejected_rows=invalid,
        duplicate_ids=duplicates,
    )
