"""Outbound Telegram and Discord transports. No incoming bot gateway required."""
import json
import os
from urllib import request
from urllib.parse import urlsplit

from .models import Destination, Event, Provenance

TELEGRAM_MAX_CHARS = 3900
DISCORD_MAX_CHARS = 1900


class PublishError(Exception):
    """Non-secret publish failure."""


def render_plain_event(event, max_chars):
    scope = f"{event.world.network} / {event.world.name}"
    origin = event.provenance.value
    title = f"[{scope} · {origin}] {event.title}"
    # A manual reminder has no external verified source; avoid appending
    # the project homepage as though it proved the event occurred.
    suffix = "" if event.provenance == Provenance.MANUAL else f"\n\n{event.source_url}"
    available = max(0, max_chars - len(title) - len(suffix) - 2)
    return f"{title}\n\n{event.body[:available]}{suffix}"


def _post_json(url, payload, timeout=12):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "L2CommunityBot/0.1",
    })
    with request.urlopen(req, timeout=timeout) as response:
        status = response.status
        data = response.read(8192)
    return status, data


def send_event(destination: Destination, event: Event, language: str,
               credential_env=None, post_json=None) -> bool:
    """Send a preformatted source event without AI translation.

    The language is the subscription's requested language; translation is a
    later separate stage. Never expose secret addresses, tokens or URLs.
    """
    env = os.environ if credential_env is None else credential_env
    post = _post_json if post_json is None else post_json
    address = env.get(destination.address_env, "")
    if not address:
        return False
    try:
        if destination.kind == "telegram":
            token = env.get(destination.token_env, "") if destination.token_env else ""
            if not token:
                return False
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": address,
                "text": render_plain_event(event, TELEGRAM_MAX_CHARS),
                "disable_web_page_preview": True,
            }
            status, response = post(url, payload)
            return status == 200 and json.loads(response).get("ok") is True
        if destination.kind == "discord":
            parsed = urlsplit(address)
            if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "discordapp.com"} or not parsed.path.startswith("/api/webhooks/"):
                return False
            if parsed.username or parsed.password or parsed.fragment:
                return False
            url = address + ("&" if parsed.query else "?") + "wait=true"
            payload = {
                "content": render_plain_event(event, DISCORD_MAX_CHARS),
                "allowed_mentions": {"parse": []},
            }
            status, response = post(url, payload)
            return status in (200, 201) and bool(response)
        return False
    except Exception:
        # urllib errors can include token/webhook URLs. Swallow and report
        # only sanitized failure to the router.
        return False
