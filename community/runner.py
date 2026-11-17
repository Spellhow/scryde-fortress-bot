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
from .schedules import due_reminders
from .relevance import filter_events
from .source_limits import FetchBudget, FetchUnavailable
from .source_health import SourceHealth
from .legacy_telegram_bridge import suppress_legacy_public_news
from .legacy_forum_bridge import suppress_legacy_forum_post


def _legacy_suppressed(state, source, destination_id, event):
    return (
        suppress_legacy_public_news(state, source, destination_id, event)
        or suppress_legacy_forum_post(state, source, destination_id, event)
    )


@dataclass(frozen=True)
class RunSummary:
    sources_checked: int
    events_seen: int
    subscriptions_initialized: int
    attempts: int
    sent: int
    errors: tuple = ()
    deferred_sources: int = 0


def _init_key(source, subscription):
    """Changing a subscription's filters forces its own safe first-run warm start."""
    # Numbered pages are the same official, validated forum thread. Changing
    # page-17 to page-18 must NOT silently warm-start again and lose newly
    # visible posts. A changed thread/domain/kind still requires a new source.
    source_identity = (
        "https://board.scryde.net/threads/obnovlenija.30694"
        if source.kind == "scryde_forum" else source.url
    )
    return "warm:" + digest([
        source.id, source.world.identity, source.kind, source_identity, source.selector,
        subscription.destination_id,
        sorted(subscription.event_types), sorted(subscription.source_ids),
        sorted(subscription.clans), subscription.language,
        sorted(source.include_keywords), sorted(source.exclude_keywords),
    ])


def run(config, state: DeliveryState, *, fetch=fetch_public_text,
        send=send_event, credentials=None, now=None, dry_run=False):
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("now must have timezone")
    checked = seen = warmed = attempts = sent = deferred = 0
    errors = []
    fetch_budget = FetchBudget()
    health = SourceHealth(state)
    failed_urls_this_run = set()
    for source in config.sources:
        if not source.enabled:
            continue
        parser = PARSERS.get(source.kind)
        is_l2dex = source.kind == "l2dex_castles"
        if parser is None and not is_l2dex:
            errors.append(f"{source.id}: adapter unavailable")
            continue
        checked += 1
        if not dry_run and not health.ready(source.url, now):
            deferred += 1
            continue
        snapshot_key = state_key(source.id, source.world, source.url) if is_l2dex else None
        candidate_snapshot = None
        try:
            payload = fetch_budget.read(source.url, fetch)
            if is_l2dex:
                parsed_castles = parse_castles(payload)
                events, candidate_snapshot = diff_castles(
                    state.cursors.get(snapshot_key), parsed_castles, source, now
                )
            else:
                events = filter_events(list(parser(payload, source, now)), source)
        except Exception as exc:
            # Only genuine HTTP fetch failures receive a delayed retry;
            # per-domain budgets and parser errors are handled separately.
            if isinstance(exc, FetchUnavailable) and not dry_run and source.url not in failed_urls_this_run:
                health.fail(source.url, now)
                failed_urls_this_run.add(source.url)
            # Do not expose source URLs/tokens/response bodies in errors.
            errors.append(f"{source.id}: source failure ({type(exc).__name__})")
            continue
        if not dry_run:
            health.recover(source.url)
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
                        if (sub.matches(event) and not _legacy_suppressed(
                                state, source, sub.destination_id, event)):
                            state.mark_delivered(sub.destination_id, event.event_id, int(now.timestamp()))
                    state.cursors[marker] = "initialized"
            else:
                active_subs.append(sub)
        if dry_run:
            continue
        outcome = dispatch_events(
            events, active_subs, config.destinations, state,
            lambda dest, ev, lang: send(dest, ev, lang, credentials),
            now=now,
            suppress=lambda destination_id, event: _legacy_suppressed(
                state, source, destination_id, event
            ),
        )
        attempts += outcome.attempted
        sent += outcome.sent
        errors.extend(outcome.errors)
        # A castle delta can be retried only if we keep the pre-delta
        # snapshot when any destination failed. Successful destinations are
        # independently marked delivered and will not get a duplicate.
        if is_l2dex and not outcome.errors:
            state.cursors[snapshot_key] = candidate_snapshot
    # Manual schedules need no browser, remote feed or warm-start. A reminder
    # only exists inside its configured UTC-aware delivery window; replay is
    # guarded by the same per-destination delivery keys as public feeds.
    scheduled = due_reminders(config.schedules, now)
    seen += len(scheduled)
    if not dry_run and scheduled:
        subs = [
            sub for sub in config.subscriptions
            if not sub.source_ids or "manual_schedule" in sub.source_ids
        ]
        outcome = dispatch_events(
            scheduled, subs, config.destinations, state,
            lambda dest, ev, lang: send(dest, ev, lang, credentials), now=now,
        )
        attempts += outcome.attempted
        sent += outcome.sent
        errors.extend(outcome.errors)
    return RunSummary(checked, seen, warmed, attempts, sent, tuple(errors), deferred)
