"""Outbound Telegram and Discord transports. No incoming bot gateway required."""
import json
import os
import re
from urllib import request
from urllib.parse import urlsplit

from .models import Destination, Event, Provenance

TELEGRAM_MAX_CHARS = 3900
DISCORD_MAX_CHARS = 1900


class PublishError(Exception):
    """Non-secret publish failure."""


def _units(text):
    """Conservative cross-platform message length (UTF-16 code units)."""
    return len(text.encode("utf-16-le")) // 2


def _truncate(text, budget):
    """Clamp even emoji-heavy text without splitting UTF-16 surrogate pairs."""
    if budget <= 0:
        return ""
    if _units(text) <= budget:
        return text
    room = budget - 1
    result = []
    used = 0
    for character in text:
        step = 2 if ord(character) > 0xFFFF else 1
        if used + step > room:
            break
        result.append(character)
        used += step
    return "".join(result) + "…"


def render_plain_event(event, max_chars):
    """Never exceed Telegram/Discord limits, even for unusual source content."""
    if not isinstance(max_chars, int) or max_chars < 20:
        raise ValueError("message size limit must be at least 20")
    scope = f"{event.world.network} / {event.world.name}"
    heading = f"[{scope} · {event.provenance.value}] {event.title}"
    heading = _truncate(heading, max_chars // 3)
    suffix = "" if event.provenance == Provenance.MANUAL else f"\n\n{event.source_url}"
    # A huge URL cannot be rendered usefully. Keep message valid instead of
    # allowing every run to fail the same Telegram/Discord length limit.
    if _units(suffix) > max_chars // 3:
        suffix = ""
    available = max_chars - _units(heading) - _units(suffix) - 2
    return heading + "\n\n" + _truncate(event.body, available) + suffix


def _post_json(url, payload, timeout=12):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "L2CommunityBot/0.1",
    })
    with request.urlopen(req, timeout=timeout) as response:
        status = response.status
        data = response.read(8192)
    return status, data


def _confirmed_telegram_message(status, response):
    if status != 200:
        return False
    decoded = json.loads(response)
    if not isinstance(decoded, dict) or decoded.get("ok") is not True:
        return False
    message = decoded.get("result")
    return (
        isinstance(message, dict)
        and type(message.get("message_id")) is int
        and message["message_id"] > 0
    )


def _confirmed_discord_message(status, response):
    if status not in (200, 201):
        return False
    decoded = json.loads(response)
    return (
        isinstance(decoded, dict)
        and isinstance(decoded.get("id"), str)
        and decoded["id"].isdigit()
    )


def _official_discord_webhook(address):
    parts = urlsplit(address)
    return (
        parts.scheme == "https"
        and parts.hostname in {"discord.com", "discordapp.com"}
        and parts.port in (None, 443)
        and not parts.username
        and not parts.password
        and not parts.fragment
        and not parts.query
        and re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+", parts.path) is not None
    )


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
            return _confirmed_telegram_message(status, response)
        if destination.kind == "discord":
            if not _official_discord_webhook(address):
                return False
            url = address + "?wait=true"
            payload = {
                "content": render_plain_event(event, DISCORD_MAX_CHARS),
                "allowed_mentions": {"parse": []},
            }
            status, response = post(url, payload)
            return _confirmed_discord_message(status, response)
        return False
    except Exception:
        # urllib errors can include token/webhook URLs. Swallow and report
        # only sanitized failure to the router.
        return False
