"""GitHub-only community feed orchestrator.

Sources fetched once per run; all destinations consume normalized events.
Use safe adapters only; original Scryde production pipeline remains separate.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .adapters.feeds import PARSERS
from .adapters.l2dex import parse_castles, diff_castles, state_key
from .fetch import fetch_public_text
from .models import digest
from .publishers import send_event
from .router import dispatch_events
from .state import DeliveryState


@dataclass(frozen=True)
class RunSummary:
    sources_checked: int
    events_seen: int
    subscriptions_initialized: int
    attempts: int
    sent: int
    errors: tuple = ()


def _init_key(source, subscription):
    """Changing a subscription's filters forces its own safe first-run warm start."""
    return "warm:" + digest([
        source.id, source.world.identity, subscription.destination_id,
        sorted(subscription.event_types), sorted(subscription.source_ids),
        sorted(subscription.clans), subscription.language,
    ])


def run(config, state: DeliveryState, *, fetch=fetch_public_text,
        send=send_event, credentials=None, now=None, dry_run=False):
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("now must have timezone")
    checked = seen = warmed = attempts = sent = 0
    errors = []
    for source in config.sources:
        if not source.enabled:
            continue
        parser = PARSERS.get(source.kind)
        is_l2dex = source.kind == "l2dex_castles"
        if parser is None and not is_l2dex:
            errors.append(f"{source.id}: adapter unavailable")
            continue
        checked += 1
        snapshot_key = state_key(source.id, source.world) if is_l2dex else None
        candidate_snapshot = None
        try:
            payload = fetch(source.url)
            if is_l2dex:
                parsed_castles = parse_castles(payload)
                events, candidate_snapshot = diff_castles(
                    state.cursors.get(snapshot_key), parsed_castles, source, now
                )
            else:
                events = list(parser(payload, source, now))
        except Exception as exc:
            # Do not expose source URLs/tokens/response bodies in errors.
            errors.append(f"{source.id}: source failure ({type(exc).__name__})")
            continue
        seen += len(events)
        active_subs = []
        for sub in config.subscriptions:
            if sub.world.identity != source.world.identity:
                continue
            if sub.source_ids and source.id not in sub.source_ids:
                continue
            marker = _init_key(source, sub)
            if marker not in state.cursors:
                warmed += 1
                if not dry_run:
                    for event in events:
                        if sub.matches(event):
                            state.mark_delivered(sub.destination_id, event.event_id, int(now.timestamp()))
                    state.cursors[marker] = "initialized"
            else:
                active_subs.append(sub)
        if dry_run:
            continue
        outcome = dispatch_events(events, active_subs, config.destinations, state,
                                  lambda dest, ev, lang: send(dest, ev, lang, credentials),
                                  now=now)
        attempts += outcome.attempted
        sent += outcome.sent
        errors.extend(outcome.errors)
        # A castle delta can be retried only if we keep the pre-delta
        # snapshot when any destination failed. Successful destinations are
        # independently marked delivered and will not get a duplicate.
        if is_l2dex and not outcome.errors:
            state.cursors[snapshot_key] = candidate_snapshot
    return RunSummary(checked, seen, warmed, attempts, sent, tuple(errors))
