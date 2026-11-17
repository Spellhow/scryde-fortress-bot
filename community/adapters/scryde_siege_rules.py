"""Pure shared BSOE siege alert decisions.

Both the authoritative legacy notification handler and the Community Bot
read-only candidate projector use these *same* conditionals. The functions
do not import transport, network or state persistence; they never mutate data.
"""


def _attack_names(values):
    return sorted(
        value if isinstance(value, str) else value.get("name", "")
        for value in values
    )


def defence_attack_changed(previous, attackers, siege_at):
    """A new siege, changed attack clan or changed siege time needs an alert."""
    return (
        not previous.get("notified_siege")
        or _attack_names(previous.get("last_attackers", []))
        != _attack_names(attackers)
        or siege_at != previous.get("last_siege_at", 0)
    )


def defence_reminder_due(previous, siege_at, now):
    """One early defence reminder, at least 90 minutes after first notice."""
    first = previous.get("siege_first_notify", 0)
    mins_left = (siege_at - now) // 60
    return bool(
        previous.get("notified_siege")
        and not previous.get("notified_reminder")
        and 0 < mins_left <= 25
        and first
        and now - first >= 90 * 60
    )


def defence_cancellation_action(previous, now):
    """Whether an ended/withdrawn registration needs a cancellation alert.

    Caller applies this only after trusted observed absence of attackers.
    Returns 'notify', 'expire' (event already started), or 'none'.
    """
    if not previous.get("notified_siege"):
        return "none"
    siege_at = previous.get("last_siege_at", 0)
    if siege_at and now >= siege_at:
        return "expire"
    return "notify"


def own_attack_action(previous, siege_at, now):
    """Existing registration, new date or early reminder (none/register/remind)."""
    if not previous.get("notified") or siege_at != previous.get("siege_at", 0):
        return "register"
    secs_left = siege_at - now if siege_at else 0
    notified_at = int(previous.get("notified_at", 0) or 0)
    enough_gap = not notified_at or now - notified_at >= 30 * 60
    if (
        not previous.get("notified_reminder")
        and 0 < secs_left <= 30 * 60
        and enough_gap
    ):
        return "remind"
    return "none"


def missing_own_attack_action(previous, now):
    """Trusted absent attack row: expire silently if siege time has arrived."""
    siege_at = previous.get("siege_at", 0)
    return "expire" if siege_at and now >= siege_at else "cancel"
