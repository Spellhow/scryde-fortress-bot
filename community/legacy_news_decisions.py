"""Side-effect-free decision rules for the BSOE moderation queue.

The legacy runtime calls the same pure function used by a read-only replay,
without moving publication, approval or delivery into the new core yet.
No source text, user identifiers, or Telegram API data is handled here.
"""

from collections import Counter

ACTIVE_STATUSES = frozenset(("pending", "approved"))
DECISION_CATEGORIES = (
    "ignore",
    "expire_age",
    "wait_schedule",
    "wait_debug",
    "expire_late",
    "publish",
)


def classify_news_queue_item(
    item, *, now, expire_hours, grace_minutes, target_chat
):
    """Return the legacy queue action without changing the supplied item.

    Use the same integer coercions and boundary checks as the existing runner.
    Publishing is only a candidate until the transport confirms delivery.
    """
    status = item.get("status")
    if status not in ACTIVE_STATUSES:
        return "ignore"
    if status == "pending" and int(item.get("created_at", 0) or 0) < (
        now - expire_hours * 60 * 60
    ):
        return "expire_age"

    publish_after = int(item.get("publish_after", 0) or 0)
    if now < publish_after:
        return "wait_schedule"
    if target_chat == "debug":
        return "wait_debug"

    # Explicit approval deliberately bypasses the auto-publish grace window.
    if status == "pending" and publish_after > 0:
        deadline = publish_after + max(0, grace_minutes) * 60
        if now > deadline:
            return "expire_late"
    return "publish"


def summarize_legacy_news_queue(
    state, *, now, expire_hours, grace_minutes, target_chat
):
    """Read-only aggregate; never print source data or arbitrary status labels."""
    if not isinstance(state, dict):
        raise ValueError("invalid legacy state")
    report = {
        "format": "legacy-news-queue-parity-v1",
        "cutover_authorized": False,
        "sections": {},
    }
    for name in ("news", "forum_news"):
        section = state.get(name, {})
        if not isinstance(section, dict):
            raise ValueError("invalid legacy news section")
        items = section.get("pending", [])
        if not isinstance(items, list):
            raise ValueError("invalid legacy moderation queue")
        counts = Counter()
        for item in items:
            if not isinstance(item, dict):
                counts["ignore"] += 1
                continue
            try:
                result = classify_news_queue_item(
                    item,
                    now=now,
                    expire_hours=expire_hours,
                    grace_minutes=grace_minutes,
                    target_chat=target_chat,
                )
            except (ValueError, TypeError, OverflowError, AttributeError):
                counts["invalid"] += 1
                continue
            counts[result] += 1
        report["sections"][name] = {
            "items": len(items),
            **{key: counts[key] for key in DECISION_CATEGORIES},
            "invalid": counts["invalid"],
        }
    return report
