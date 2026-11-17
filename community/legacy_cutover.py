"""Prepare *both* legacy public-source checkpoints in a single atomic candidate.

This migration intentionally does NOT carry private moderation texts,
cross-source approval state, siege flags or Telegram callback offsets.
No production cutover authorization is returned.
"""
from .legacy_telegram_bridge import prepare_public_telegram_watermark
from .legacy_forum_bridge import prepare_public_forum_watermark
from .state import DeliveryState


def prepare_bsoe_history_checkpoints(old, config, *, telegram_source,
                                     forum_source, destination, current):
    """A pure operation; either both markers are valid or none is returned."""
    if telegram_source == forum_source:
        raise ValueError("different source aliases are required")
    if not isinstance(current, DeliveryState):
        raise ValueError("current state must be loaded and validated")
    first = prepare_public_telegram_watermark(
        old, config, telegram_source, destination, current
    )
    both = prepare_public_forum_watermark(
        old, config, forum_source, destination, first
    )
    return both
