"""HTTPS-only public reader with DNS/IP pinning and bounded response body.

Rejects private/reserved IPs and redirects. No proxies and no redirect-following.
This is intended for publicly accessible RSS/HTML/JSON sources, not auth bypass.
"""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit

MAX_BODY = 512 * 1024
MAX_TIMEOUT = 12


class FetchError(Exception):
    """Safe error category; do not include source credentials in errors."""


def resolve_public_https(url):
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise FetchError("invalid HTTPS source")
        if parts.port not in (None, 443):
            raise FetchError("unsupported HTTPS port")
        host = parts.hostname
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise FetchError("local host is forbidden")
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addrs = [record[4][0] for record in records]
        if not addrs or any(not ipaddress.ip_address(ip).is_global for ip in addrs):
            raise FetchError("source resolves to non-public IP address")
        return parts, addrs[0]
    except (ValueError, socket.gaierror, UnicodeError) as exc:
        raise FetchError("invalid or unavailable source host") from exc


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname, pinned_ip, timeout):
        super().__init__(hostname, 443, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self):
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def fetch_public_text(url, max_bytes=MAX_BODY):
    """Fetch one source. No redirects, no internal hosts, max 512 KiB."""
    if not 0 < max_bytes <= MAX_BODY:
        raise ValueError("invalid max_bytes")
    parts, pinned_ip = resolve_public_https(url)
    conn = PinnedHTTPSConnection(parts.hostname, pinned_ip, MAX_TIMEOUT)
    try:
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn.request("GET", path, headers={
            "Host": parts.hostname,
            "User-Agent": "Lineage2CommunityBot/0.1 (public-source-check)",
            "Accept": "text/html, application/json, application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Accept-Encoding": "identity",
            "Connection": "close",
        })
        response = conn.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            raise FetchError("redirects must be configured as a new explicit source")
        if response.status != 200:
            raise FetchError(f"source returned HTTP {response.status}")
        length = response.getheader("Content-Length")
        if length and length.isdigit() and int(length) > max_bytes:
            raise FetchError("source body too large")
        content_type = (response.getheader("Content-Type") or "").lower()
        if not any(kind in content_type for kind in ("text/", "application/json", "application/xml", "application/rss+xml", "application/atom+xml")):
            raise FetchError("unsupported source content type")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise FetchError("source body too large")
        if response.getheader("Content-Encoding") not in (None, "identity"):
            raise FetchError("compressed responses are unsupported")
        return data.decode("utf-8-sig", errors="replace")
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise FetchError(f"source transport error ({type(exc).__name__})") from exc
    finally:
        conn.close()
