"""Read-only public source preview, safe for a manual GitHub Actions run."""
from datetime import datetime, timezone
import re

from .adapters.feeds import PARSERS
from .adapters.l2dex import parse_castles
from .relevance import filter_events
from .source_limits import FetchBudget
from .fetch import fetch_public_text


def _short(value, limit=110):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))[:limit]


def preview_sources(config, *, selected="", fetch=fetch_public_text,
                    source_limit=5, sample_limit=5, now=None):
    """Return summaries only: never publish, store state or call an AI model.

    The caller controls which **public** source to inspect by its configured
    alias; never accepts arbitrary URLs outside the validated config.
    """
    if not 1 <= source_limit <= 5 or not 1 <= sample_limit <= 5:
        raise ValueError("preview bounds must be between 1 and 5")
    now = now or datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("preview time requires timezone")
    requested = [
        source for source in config.sources
        if source.enabled and (not selected or source.id == selected)
    ]
    if selected and not requested:
        raise ValueError("requested source not present or not enabled")
    budget = FetchBudget()
    results = []
    for source in requested[:source_limit]:
        item = {
            "source": _short(source.id, 80),
            "kind": source.kind,
            "world": _short(f"{source.world.network}/{source.world.name}", 90),
            "event_count": 0,
            "samples": [],
        }
        try:
            content = budget.read(source.url, fetch)
            if source.kind == "l2dex_castles":
                castles = parse_castles(content)
                item["event_count"] = len(castles)
                item["samples"] = [
                    _short(f"{castle.name}: {castle.owner or 'owner unknown'}")
                    for _, castle in sorted(castles.items(), key=lambda pair: int(pair[0]))[:sample_limit]
                ]
            else:
                parser = PARSERS.get(source.kind)
                if parser is None:
                    raise ValueError("unsupported public source kind")
                events = filter_events(list(parser(content, source, now)), source)
                item["event_count"] = len(events)
                item["samples"] = [_short(event.title) for event in events[:sample_limit]]
        except Exception as exc:
            # Avoid exposing public response content, user configuration or
            # token-bearing network exception text in logs.
            item["error"] = type(exc).__name__
        results.append(item)
    return {
        "sources_available": len(requested),
        "sources_previews": len(results),
        "sources_skipped": max(0, len(requested) - len(results)),
        "results": results,
    }
