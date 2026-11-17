"""Pure retention policy for legacy BSOE moderation queue.

Active moderation requests are never silently truncated as history grows.
"""
ACTIVE_STATUSES = frozenset({"pending", "approved"})
MAX_HISTORICAL_NEWS_ITEMS = 50
MAX_ACTIVE_NEWS_ITEMS = 200


def _is_active(item):
    return (
        isinstance(item, dict)
        and isinstance(item.get("status"), str)
        and item["status"] in ACTIVE_STATUSES
    )


def active_moderation_count(items):
    return sum(1 for item in items if _is_active(item))


def retain_news_queue(items, history_limit=MAX_HISTORICAL_NEWS_ITEMS):
    """Keep every active item plus up to N newest historical items, in order.

    Does not mutate item contents or reorder the source moderation queue.
    The ingestion path guards against adding new active posts once the active
    queue reaches MAX_ACTIVE_NEWS_ITEMS.
    """
    if not isinstance(items, list):
        raise ValueError("legacy news queue must be a list")
    if type(history_limit) is not int or history_limit < 0:
        raise ValueError("history limit must be a nonnegative integer")
    historical = [
        index for index, item in enumerate(items)
        if not _is_active(item)
    ]
    keep_history = set(historical[-history_limit:]) if history_limit else set()
    return [
        item for index, item in enumerate(items)
        if index in keep_history or _is_active(item)
    ]
