"""Explicit one-message probe for an authorized community destination.

This is intentionally not integrated into a recurring poller. It cannot
read/modify delivery state or scrape a public website.
"""
from datetime import datetime, timezone

from .models import Event, Provenance
from .publishers import send_event


def probe_destination(config, alias, credentials, *, sender=send_event, at=None):
    """Send one clearly labeled non-game event; return API-confirmed success.

    Missing or unsubscribed destinations are rejected before invoking sender.
    No secret or numeric destination address is returned.
    """
    if not isinstance(alias, str) or not alias.strip():
        return False
    dest = config.destinations.get(alias)
    if dest is None:
        return False
    subscriptions = [sub for sub in config.subscriptions if sub.destination_id == alias]
    if not subscriptions:
        return False
    if not credentials.get(dest.address_env):
        return False
    if dest.kind == "telegram" and (not dest.token_env or not credentials.get(dest.token_env)):
        return False
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    world = subscriptions[0].world
    notification = Event(
        world=world,
        source_id="community-diagnostics",
        external_id="manual-delivery-probe",
        kind="manual_delivery_test",
        title="🧪 Community Bot delivery test",
        body=(
            "This is one manually requested test of Telegram/Discord delivery. "
            "No in-game siege, boss kill or other event was observed."
        ),
        source_url="https://github.com/",
        provenance=Provenance.MANUAL,
        observed_at=now,
    )
    return sender(dest, notification, subscriptions[0].language, credentials) is True
