"""Bounded, opt-in checkpoint bridge for official Scryde public forum updates.

Legacy forum moderation and live Telegram approvals stay in the old bot.
The marker is a public post watermark scoped to ONE destination and thread.
"""
import re

from .legacy_telegram_bridge import _check_legacy_news, _valid_post_number
from .models import Provenance, digest
from .state import DeliveryState

THREAD_IDENTITY = "board.scryde.net/threads/obnovlenija.30694"
THREAD_PATH = re.compile(r"/threads/obnovlenija\.30694(?:/page-[1-9][0-9]*)?/?")


def _require_legacy_forum_source(source):
    if (source.kind != "scryde_forum"
            or source.world.network.casefold() != "scryde"
            or source.world.name.casefold() != "x1000"
            or source.world.chronicle.strip()):
        raise ValueError("only Scryde x1000 official public forum source is supported")
    from urllib.parse import urlsplit
    parts = urlsplit(source.url)
    if (parts.scheme != "https" or parts.hostname != "board.scryde.net"
            or not THREAD_PATH.fullmatch(parts.path)
            or parts.query or parts.fragment or parts.username or parts.password):
        raise ValueError("official Scryde updates thread required")


def forum_watermark_key(source, destination_id):
    _require_legacy_forum_source(source)
    # Bind the thread identity rather than a page number. An administrator
    # can update the configured current page without forgetting old post IDs.
    return "legacy-forum-watermark:" + digest((
        source.world.identity,
        source.id.casefold(),
        source.kind,
        THREAD_IDENTITY,
        destination_id.casefold(),
    ))


def prepare_public_forum_watermark(legacy_state, config, source_alias,
                                   destination_alias, current_state):
    if not isinstance(legacy_state, dict):
        raise ValueError("legacy state must be an object")
    source = next((item for item in config.sources if item.id == source_alias), None)
    if source is None:
        raise ValueError("configured forum source alias not found")
    _require_legacy_forum_source(source)
    if not source.enabled:
        raise ValueError("public forum source must be explicitly enabled")
    destination = config.destinations.get(destination_alias)
    if destination is None or destination.kind != "telegram":
        raise ValueError("old BSOE forum identity can only target one Telegram destination")
    relevant = [
        sub for sub in config.subscriptions
        if sub.destination_id == destination_alias
        and sub.world.identity == source.world.identity
        and (not sub.source_ids or source.id in sub.source_ids)
        and (not sub.event_types or "news" in sub.event_types)
    ]
    if len(relevant) != 1 or relevant[0].clans:
        raise ValueError("unambiguous, unfiltered by clan forum subscription required")
    last_seen = _check_legacy_news(legacy_state.get("forum_news"))
    output = DeliveryState(dict(current_state.delivered), dict(current_state.cursors))
    key = forum_watermark_key(source, destination_alias)
    previous = output.cursors.get(key)
    if previous is not None and previous != str(last_seen):
        raise ValueError("existing forum checkpoint differs; no automatic rewind")
    output.cursors[key] = str(last_seen)
    return output


def suppress_legacy_forum_post(state, source, destination_id, event):
    if source.kind != "scryde_forum":
        return False
    if event.provenance != Provenance.OBSERVED or event.kind != "news":
        return False
    if event.world.identity != source.world.identity or event.source_id != source.id:
        return False
    _require_legacy_forum_source(source)
    checkpoint = state.cursors.get(forum_watermark_key(source, destination_id))
    if checkpoint is None:
        return False
    if not checkpoint.isascii() or not checkpoint.isdecimal():
        raise ValueError("invalid forum source checkpoint")
    number = int(checkpoint)
    if not _valid_post_number(number):
        raise ValueError("invalid forum source checkpoint")
    match = re.fullmatch(r"forum-post:([1-9][0-9]*)", event.external_id)
    if match is None or len(match.group(1)) > 13:
        return False
    return int(match.group(1)) <= number
