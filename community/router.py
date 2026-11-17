"""Source-independent event-to-community fanout."""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class DispatchOutcome:
    attempted: int
    sent: int
    skipped: int
    errors: tuple


def dispatch_events(events, subscriptions, destinations, state, sender, now=None):
    """Return dispatch counters; caller persists state.

    Not exactly-once across process death after a remote send and before
    persisting state. A failed destination cannot block another destination.
    """
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("current time must include timezone")
    source_events = list(events)  # event source polled exactly once by caller
    attempted = sent = skipped = 0
    errors = []
    # One outbound attempt per destination + event per run, even if several
    # overlapping subscriptions match it and the first send fails.
    attempted_keys = set()
    for subscription in subscriptions:
        target = destinations.get(subscription.destination_id)
        if target is None:
            errors.append(f"missing destination: {subscription.destination_id}")
            continue
        for event in source_events:
            if not subscription.matches(event):
                continue
            if state.was_delivered(target.id, event.event_id):
                skipped += 1
                continue
            attempt_key = (target.id.casefold(), event.event_id)
            if attempt_key in attempted_keys:
                skipped += 1
                continue
            attempted_keys.add(attempt_key)
            attempted += 1
            try:
                success = sender(target, event, subscription.language)
            except Exception as exc:
                errors.append(f"delivery error: {target.id} ({type(exc).__name__})")
                continue
            if success:
                state.mark_delivered(target.id, event.event_id, int(now.timestamp()))
                sent += 1
            else:
                errors.append(f"delivery rejected: {target.id}")
    return DispatchOutcome(attempted, sent, skipped, tuple(errors))
