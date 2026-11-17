"""Explicit, bounded import of one public BSOE Telegram news watermark.

Legacy moderation and forum queues are NOT migrated. This only suppresses
already-seen historical posts for one validated public source/destination.
Do not enable a BSOE cutover based on this partial bridge.
"""
import re
from .models import Provenance, digest
from .state import DeliveryState

PUBLIC_BSOE_CHANNEL = "https://t.me/s/scryde"
MAX_PUBLIC_POST_ID = 10**12
FINISHED_STATUSES = frozenset({"published", "cancelled", "expired"})


def _require_bsoe_source(source):
    if (
        source.kind != "telegram_public"
        or source.url != PUBLIC_BSOE_CHANNEL
        or source.world.network.casefold() != "scryde"
        or source.world.name.casefold() != "x1000"
        or source.world.chronicle.strip()
    ):
        raise ValueError("only the original public Scryde x1000 feed can use this bridge")


def watermark_key(source, destination_id):
    _require_bsoe_source(source)
    return "legacy-tg-watermark:" + digest((
        source.world.identity,
        source.id.casefold(),
        source.kind,
        source.url,
        destination_id.casefold(),
    ))


def _valid_post_number(value, *, allow_zero=False):
    return (
        type(value) is int
        and (0 if allow_zero else 1) <= value <= MAX_PUBLIC_POST_ID
    )


def _check_legacy_news(section):
    if not isinstance(section, dict):
        raise ValueError("missing legacy public news state")
    last_seen = section.get("last_seen_id")
    sent = section.get("sent_ids")
    pending = section.get("pending")
    if not _valid_post_number(last_seen):
        raise ValueError("missing valid public source cursor")
    if not isinstance(sent, list) or not isinstance(pending, list):
        raise ValueError("malformed legacy news history")
    if any(not _valid_post_number(num) or num > last_seen for num in sent):
        raise ValueError("legacy handled post exceeds source cursor")
    for item in pending:
        if not isinstance(item, dict):
            raise ValueError("malformed legacy pending post")
        if item.get("status") not in FINISHED_STATUSES:
            raise ValueError("active or unknown moderation cannot be imported")
        ident = item.get("post_id")
        if not _valid_post_number(ident) or ident > last_seen:
            raise ValueError("invalid legacy pending source ID")
    return last_seen


def prepare_public_telegram_watermark(legacy_state, config, source_alias,
                                       destination_alias, current_state):
    """Return a NEW DeliveryState, keeping existing delivery evidence.

    This partial import is intentionally scoped to exactly one original BSOE
    public Telegram source and one destination. The state has a hashed marker
    and numeric public post watermark, not a private chat ID or post text.
    """
    if not isinstance(legacy_state, dict):
        raise ValueError("legacy state must be an object")
    source = next((s for s in config.sources if s.id == source_alias), None)
    if source is None:
        raise ValueError("configured source alias not found")
    _require_bsoe_source(source)
    if not source.enabled:
        raise ValueError("source must be enabled")
    destination = config.destinations.get(destination_alias)
    if destination is None or destination.kind != "telegram":
        raise ValueError("destination must be an existing Telegram alias")
    relevant = [
        sub for sub in config.subscriptions
        if sub.destination_id == destination_alias
        and sub.world.identity == source.world.identity
        and (not sub.source_ids or source.id in sub.source_ids)
        and (not sub.event_types or "news" in sub.event_types)
    ]
    if len(relevant) != 1:
        # Do not infer which alias, world, filter, or moderation policy is
        # intended when the configuration contains overlap/ambiguity.
        raise ValueError("exactly one matching Telegram news subscription is required")
    if relevant[0].clans:
        raise ValueError("legacy news cannot be mapped to a clan-filtered subscription")
    old = legacy_state.get("news")
    last_seen = _check_legacy_news(old)

    # Retain the existing public-state receipts/cursors. Refuse replacing an
    # existing watermark so retries do not silently rewind a cutover.
    output = DeliveryState(dict(current_state.delivered), dict(current_state.cursors))
    key = watermark_key(source, destination_alias)
    previous = output.cursors.get(key)
    if previous is not None and previous != str(last_seen):
        raise ValueError("watermark already exists with a different checkpoint")
    output.cursors[key] = str(last_seen)
    return output


def suppress_legacy_public_news(state, source, destination_id, event):
    """Suppress only older original public Telegram posts for one destination.

    This does NOT count a suppressed post as delivered.
    """
    if source.kind != "telegram_public" or source.url != PUBLIC_BSOE_CHANNEL:
        return False
    if event.provenance != Provenance.OBSERVED or event.kind != "news":
        return False
    if event.source_id != source.id or event.world.identity != source.world.identity:
        return False
    _require_bsoe_source(source)
    checkpoint = state.cursors.get(watermark_key(source, destination_id))
    if checkpoint is None:
        return False
    if not checkpoint.isascii() or not checkpoint.isdecimal():
        # Bad state must not be silently interpreted as a permissive switch.
        raise ValueError("invalid legacy source watermark")
    value = int(checkpoint)
    if not _valid_post_number(value):
        raise ValueError("invalid legacy source watermark")
    match = re.fullmatch(r"scryde/([1-9][0-9]*)", event.external_id.casefold())
    if match is None:
        # Other message IDs, sources, or formats are not suppressed.
        return False
    digits = match.group(1)
    if len(digits) > 13:
        return False
    post_number = int(digits)
    return post_number <= value
