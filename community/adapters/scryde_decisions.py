"""Pure read-only projection of *candidate* legacy siege notification decisions.

This models observable BSOE decisions for side-by-side parity tests, not
delivery success or a replacement state machine. Absolutely no side effects.
"""
from collections import Counter
from dataclasses import dataclass

from .scryde_rows import get_attackers, valid_scryde_ranking_rows


@dataclass(frozen=True)
class Decision:
    kind: str
    object_id: str


@dataclass(frozen=True)
class DecisionProjection:
    decisions: tuple[Decision, ...]
    malformed_rows: int
    missing_owned_rows: int

    def summary(self):
        """Only event counts; never usernames, URLs or clan identifiers."""
        return {
            "candidates": dict(sorted(Counter(d.kind for d in self.decisions).items())),
            "malformed_rows": self.malformed_rows,
            "missing_owned_rows": self.missing_owned_rows,
        }


def _previous_objects(defence):
    tracked = defence.get("objects", {})
    tracked = dict(tracked) if isinstance(tracked, dict) else {}
    old_id = defence.get("id")
    if old_id is not None and str(old_id) not in tracked:
        tracked[str(old_id)] = defence
    return tracked


def _names(value):
    if not isinstance(value, list):
        return []
    return sorted(x if isinstance(x, str) else x.get("name", "")
                  for x in value if isinstance(x, (str, dict)))


def project_scryde_decisions(items, *, clan, object_type, defence_state,
                             attack_state, now, recent_alerts=None):
    """Predict legacy send attempts from an already-fetched ranking snapshot.

    Assumes outbound transports would succeed; does not mutate either state
    or filter candidates by platform network availability. Duplicate alert
    suppression mirrors the legacy 3-hour cache when supplied.
    """
    if object_type not in {"fortress", "castle"}:
        raise ValueError("unsupported Scryde object type")
    if not isinstance(items, list) or not isinstance(clan, str) or not clan.strip():
        raise ValueError("invalid Scryde ranking or clan")
    if type(now) is not int:
        raise ValueError("now must be a Unix timestamp")
    tracked = _previous_objects(defence_state)
    recent_alerts = recent_alerts or {}
    rows, rejected = valid_scryde_ranking_rows(items)
    by_id = {str(item["id"]): item for item in rows}
    result = []
    owned = set()

    for row in rows:
        object_id = str(row["id"])
        owner = row.get("owner")
        if not (isinstance(owner, dict) and owner.get("name") == clan):
            continue
        owned.add(object_id)
        previous = tracked.get(object_id, {})
        # Legacy resets these flags on acquiring an object for the first time.
        if previous.get("had") is not True:
            previous = {}
        attackers = get_attackers(row)
        siege_at = row.get("siege_at") or 0
        if attackers and siege_at:
            changed = (
                not previous.get("notified_siege")
                or _names(previous.get("last_attackers", [])) != sorted(attackers)
                or siege_at != previous.get("last_siege_at", 0)
            )
            sent_new_alert = False
            if changed:
                key = "{}:{}:{}:{}".format(
                    object_type, row["id"], siege_at, "|".join(sorted(attackers))
                )
                last = recent_alerts.get(key, 0)
                if not last or now - last > 3*60*60:
                    result.append(Decision("defence_attack", object_id))
                    sent_new_alert = True
            first = previous.get("siege_first_notify", 0)
            if sent_new_alert and not previous.get("notified_siege"):
                first = now
            notified = bool(previous.get("notified_siege") or sent_new_alert)
            mins_left = (siege_at-now)//60
            if (notified and not previous.get("notified_reminder")
                    and 0 < mins_left <= 25 and first
                    and now-first >= 90*60):
                result.append(Decision("defence_reminder", object_id))
        elif not attackers and previous.get("notified_siege"):
            if not previous.get("last_siege_at") or now < previous["last_siege_at"]:
                result.append(Decision("defence_cancelled", object_id))

    missing_owned = 0
    for object_id, previous in tracked.items():
        if object_id in owned or not isinstance(previous, dict):
            continue
        if previous.get("had") is True and not previous.get("notified_lost"):
            if object_id not in by_id:
                missing_owned += 1
            else:
                result.append(Decision("ownership_lost", object_id))

    attacking_ids = set()
    for row in rows:
        object_id = str(row["id"])
        attackers = get_attackers(row)
        owner = row.get("owner")
        if clan not in attackers or (isinstance(owner, dict) and owner.get("name") == clan):
            continue
        attacking_ids.add(object_id)
        previous = attack_state.get(object_id, {})
        siege_at = row.get("siege_at") or 0
        if not previous.get("notified") or siege_at != previous.get("siege_at", 0):
            result.append(Decision("our_attack", object_id))
        else:
            seconds = siege_at-now if siege_at else 0
            notified_at = int(previous.get("notified_at", 0) or 0)
            enough_gap = not notified_at or now-notified_at >= 30*60
            if (not previous.get("notified_reminder") and
                    0 < seconds <= 30*60 and enough_gap):
                result.append(Decision("our_attack_reminder", object_id))

    disappeared = set(attack_state) - attacking_ids
    if not (rejected and disappeared):
        for object_id in sorted(disappeared):
            previous = attack_state[object_id]
            siege_at = previous.get("siege_at", 0)
            if not siege_at or now < siege_at:
                result.append(Decision("our_attack_cancelled", object_id))

    return DecisionProjection(tuple(result), rejected, missing_owned)
