"""Cross-run public source failure backoff stored in existing v1 state.

Only hashed URL keys and bounded integer counters are serialized. This is
independent of message delivery keys and does not require any extra hosting.
"""
import json

from .models import digest

BASE_RETRY_MINUTES = 20
MAX_RETRY_MINUTES = 120
MAX_FAILURES = 6


def health_key(url):
    return "health:" + digest(["public-source", url])


def parser_identity(source):
    """Distinct retry key per validated parser configuration, no raw URL in state.

    Fetch failures still share an URL-wide backoff; a malformed source's
    HTML/parser must not block another source using the same public URL.
    Changing a selector or keyword scope starts a new parser identity.
    """
    return "parser:" + digest((
        source.id.casefold(), source.world.identity, source.kind,
        source.url, source.selector,
        sorted(source.include_keywords), sorted(source.exclude_keywords),
    ))


class SourceHealth:
    def __init__(self, state):
        self.state = state

    def _load(self, url):
        raw=self.state.cursors.get(health_key(url))
        if not raw:
            return (0, 0)
        try:
            data=json.loads(raw)
        except (ValueError, TypeError):
            return (0, 0)
        failures=data.get("failures") if isinstance(data, dict) else None
        retry_after=data.get("retry_after") if isinstance(data, dict) else None
        if type(failures) is not int or not 0 <= failures <= MAX_FAILURES:
            return (0, 0)
        if type(retry_after) is not int or retry_after < 0:
            return (0, 0)
        return failures,retry_after

    @staticmethod
    def _seconds(now):
        if now.utcoffset() is None:
            raise ValueError("source health time must be timezone-aware")
        return int(now.timestamp())

    def ready(self, url, now):
        timestamp=self._seconds(now)
        _,next_retry=self._load(url)
        # Ignore corrupt/unbounded future timestamps rather than blocking
        # a source forever from malformed user-edited JSON state.
        if next_retry > timestamp + MAX_RETRY_MINUTES*60+60:
            return True
        return timestamp >= next_retry

    def fail(self, url, now):
        timestamp=self._seconds(now)
        previous,_=self._load(url)
        failures=min(MAX_FAILURES,previous+1)
        delay=min(MAX_RETRY_MINUTES,BASE_RETRY_MINUTES*(2**(failures-1)))
        self.state.cursors[health_key(url)]=json.dumps({
            "failures":failures,
            "retry_after":timestamp+delay*60
        },sort_keys=True,separators=(",",":"))
        return delay

    def recover(self, url):
        self.state.cursors.pop(health_key(url),None)
