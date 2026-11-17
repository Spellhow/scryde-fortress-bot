"""Shared, side-effect-free Scryde ranking row validation.

Legacy BSOE alerts and the new read-only community adapters must agree on
which rows are trustworthy. Do not import Telegram, Gemini or browser code.
"""

def is_valid_scryde_ranking_row(item):
    """Reject partial/malformed ranking rows rather than inferring a lost siege.

    An explicit owner=None is a valid unowned/NPC row. A missing owner field
    is *unknown* data, not proof of lost ownership. A missing siege_sides field
    is tolerated for backward compatibility with non-siege ranking variants.
    """
    if not isinstance(item, dict):
        return False
    identifier = item.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier).strip():
        return False
    if not isinstance(item.get("name"), str) or not item["name"].strip():
        return False
    if "owner" not in item:
        return False
    owner = item["owner"]
    if owner is not None and (
        not isinstance(owner, dict)
        or not isinstance(owner.get("name"), str)
        or not owner["name"].strip()
    ):
        return False
    sides = item.get("siege_sides", [])
    if sides in (None, []):
        pass
    elif not isinstance(sides, dict):
        return False
    else:
        attackers = sides.get("attackers", [])
        if not isinstance(attackers, list):
            return False
        for attacker in attackers:
            if not isinstance(attacker, dict) or not isinstance(attacker.get("name"), str):
                return False
    siege_at = item.get("siege_at") or 0
    if isinstance(siege_at, bool) or not isinstance(siege_at, (int, float)) or siege_at < 0:
        return False
    return True


def valid_scryde_ranking_rows(items):
    """Skip all competing rows for the same ID, not just the later duplicate."""
    valid = {}
    competing = set()
    rejected = 0
    for item in items:
        if not is_valid_scryde_ranking_row(item):
            rejected += 1
            continue
        key = str(item["id"])
        if key in valid or key in competing:
            rejected += 1
            competing.add(key)
            valid.pop(key, None)
            continue
        valid[key] = item
    return list(valid.values()), rejected


def get_attackers(item):
    """Return only safely parsed clan names; never crash on an invalid row."""
    if not isinstance(item, dict):
        return []
    sides = item.get("siege_sides")
    if not isinstance(sides, dict):
        return []
    attackers = sides.get("attackers", [])
    if not isinstance(attackers, list):
        return []
    return [
        attacker["name"]
        for attacker in attackers
        if isinstance(attacker, dict) and isinstance(attacker.get("name"), str)
        and attacker["name"].strip()
    ]


