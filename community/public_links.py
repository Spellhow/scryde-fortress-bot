"""Conservative shared display-only HTTPS source link validation.

No network, DNS calls, link fetching, redirects, or credential logging.
Used by feed normalization and both outbound platforms; do not confuse this
with the stronger DNS/IP-pinned policy in the HTTP *fetcher*.
"""
import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit

MAX_DISPLAY_LINK_CHARS = 500
SENSITIVE_PARAMS = frozenset((
    "token", "key", "secret", "password", "pass", "api_key",
    "apikey", "access_token", "id_token", "oauth_token",
    "authorization", "auth", "signature", "sig", "session",
    "session_id", "client_secret", "private_key", "jwt",
))


def safe_public_link(url):
    """Return the unchanged URL only when suitable for public display."""
    if not isinstance(url, str) or not 0 < len(url) <= MAX_DISPLAY_LINK_CHARS:
        return None
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        # Fully qualified DNS names may have a terminal root dot, which
        # must not bypass the local/private-host display policy.
        domain = host.rstrip(".") if host else ""
        if (
            parts.scheme != "https" or not domain or "." not in domain
            or domain.endswith((".localhost", ".local", ".internal", ".lan"))
            or domain in {"localhost"}
            or parts.username or parts.password
            or parts.port not in (None, 443)
        ):
            return None
        try:
            ipaddress.ip_address(domain)
            return None
        except ValueError:
            pass
        if parts.fragment and not re.fullmatch(r"post-[1-9][0-9]{0,12}", parts.fragment):
            # Only the public Scryde forum post permalink fragment is needed.
            # Reject OAuth fragments or arbitrary fragments with credentials.
            return None
        if any(name.casefold() in SENSITIVE_PARAMS
               for name, _ in parse_qsl(parts.query, keep_blank_values=True)):
            return None
    except (ValueError, TypeError):
        return None
    return url
