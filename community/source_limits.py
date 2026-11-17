"""Per-run shared fetch budget, avoiding repeated requests to one provider."""
from urllib.parse import urlsplit

MAX_PUBLIC_REQUESTS_PER_DOMAIN = 6


class FetchBudgetExceeded(Exception):
    """Safe category for throttled requests; does not expose source URLs."""


class FetchUnavailable(Exception):
    """Safe category for a failed public fetch; does not expose response text."""


class FetchBudget:
    def __init__(self, limit=MAX_PUBLIC_REQUESTS_PER_DOMAIN):
        if type(limit) is not int or not 1 <= limit <= MAX_PUBLIC_REQUESTS_PER_DOMAIN:
            raise ValueError("public domain request limit must be 1-6")
        self.limit = limit
        self.domain_calls = {}
        self.cache = {}

    def read(self, url, fetch):
        """Fetch a URL at most once per run and no more than N URLs per host.

        Cache unsuccessful attempts too. A broken provider is not retried once
        for every game world/destination during the same GitHub Actions run.
        """
        if url not in self.cache:
            hostname = urlsplit(url).hostname
            if not hostname:
                raise FetchUnavailable("invalid public source")
            if self.domain_calls.get(hostname, 0) >= self.limit:
                raise FetchBudgetExceeded("public domain request budget exceeded")
            self.domain_calls[hostname] = self.domain_calls.get(hostname, 0) + 1
            try:
                self.cache[url] = (True, fetch(url))
            except Exception:
                # Do not re-raise errors that can include access tokens, URLs
                # or sensitive HTTP headers in their string representation.
                self.cache[url] = (False, None)
        success, payload = self.cache[url]
        if not success:
            raise FetchUnavailable("source failed during this run")
        return payload
