"""Explicit, deterministic source relevance filtering.

This is a user-configured *keyword* gate, not AI translation or an assertion
that a public post is about a specific L2 world. No regex patterns are accepted
from user configuration. Unicode word boundaries prevent x100 from matching x1000.
"""
import re


def mentions(text: str, keyword: str) -> bool:
    keyword = keyword.casefold().strip()
    if not keyword:
        return False
    return re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text.casefold()) is not None


def filter_events(events, source):
    """Return only records matching requested source scope (title/body only).

    Exclusion wins. No implicit server inference if include_keywords is empty.
    """
    include = source.include_keywords
    exclude = source.exclude_keywords
    if not include and not exclude:
        return list(events)
    result = []
    for event in events:
        content = event.title + "\n" + event.body
        if any(mentions(content, keyword) for keyword in exclude):
            continue
        if include and not any(mentions(content, keyword) for keyword in include):
            continue
        result.append(event)
    return result
