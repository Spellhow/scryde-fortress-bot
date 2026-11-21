"""Normalize public RSS/Atom, Telegram pages, JSON APIs and selected HTML."""
import hashlib
import html as html_lib
from html.parser import HTMLParser
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from community.models import Event, Provenance
from community.public_links import safe_public_link


def _plain(value, limit=3200):
    soup = BeautifulSoup(value or "", "html.parser")
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()
    return soup.get_text(" ", strip=True)[:limit]


def _event(world, source_id, external_id, title, body, link, now, kind="news"):
    if not title.strip() or not body.strip():
        return None
    # Feed links are displayed, never fetched. Avoid publishing javascript,
    # file, or credential-containing links as if they were official sources.
    if safe_public_link(link) is None:
        return None
    return Event(world=world, source_id=source_id, external_id=external_id,
                 kind=kind, title=title[:160], body=body[:3200],
                 source_url=link, provenance=Provenance.OBSERVED, observed_at=now)


def parse_rss(text, source, now=None):
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("RSS external entities are forbidden")
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(text)
    if root.tag not in {
        "rss",
        "{http://www.w3.org/2005/Atom}feed",
        "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF",
    }:
        # A challenge/error page can be well-formed XML or XHTML. Treat it
        # as a broken source, never as an empty successful feed baseline.
        raise ValueError("not an RSS or Atom document")
    events = []
    rss_items = root.findall(".//item")
    atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in rss_items:
        title = (item.findtext("title") or "").strip()
        body = _plain(item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or title)
        link = (item.findtext("link") or source.url).strip()
        eid = (item.findtext("guid") or link or title).strip()
        result = _event(source.world, source.id, eid, title, body, link, now)
        if result: events.append(result)
    namespace = "{http://www.w3.org/2005/Atom}"
    for entry in atom_entries:
        title = (entry.findtext(f"{namespace}title") or "").strip()
        body = _plain(entry.findtext(f"{namespace}summary") or entry.findtext(f"{namespace}content") or title)
        link_element = entry.find(f"{namespace}link")
        link = link_element.get("href") if link_element is not None else source.url
        eid = entry.findtext(f"{namespace}id") or link or title
        result = _event(source.world, source.id, eid, title, body, link, now)
        if result: events.append(result)
    if (rss_items or atom_entries) and not events:
        # An actual empty RSS/Atom feed is valid; one with entries that
        # *all* fail normalization cannot safely warm or advance cursors.
        raise ValueError("RSS/Atom entries unavailable after validation")
    return events


def parse_telegram_public(text, source, now=None):
    """Require trustworthy public channel post IDs before warming a source.

    Successful HTTP does not prove the returned page is an actual Telegram
    channel: anti-bot/login/error HTML may contain no messages at all.
    """
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(text, "html.parser")
    nodes = soup.select(".tgme_widget_message[data-post]")
    if not nodes:
        raise ValueError("public Telegram message elements unavailable")
    channel = urlsplit(source.url).path.rsplit("/", 1)[-1].casefold()
    events = {}
    ambiguous_ids = set()
    for node in nodes[:200]:
        raw_id = node.get("data-post", "").strip()
        match = re.fullmatch(r"([A-Za-z0-9_]{4,})/([1-9][0-9]{0,12})", raw_id)
        if not match or match.group(1).casefold() != channel:
            continue
        eid = f"{channel}/{match.group(2)}"
        content = node.select_one(".tgme_widget_message_text")
        if content is None:
            continue
        body = _plain(str(content))
        if not body:
            continue
        # The official channel/post identifier is the source of the link;
        # HTML-supplied hrefs must not redirect a post to another domain.
        link = f"https://t.me/{channel}/{match.group(2)}"
        result = _event(source.world, source.id, eid, body[:100], body, link, now)
        if result is None:
            continue
        if eid in events:
            ambiguous_ids.add(eid)
            continue
        events[eid] = result
    for eid in ambiguous_ids:
        del events[eid]
    if not events:
        raise ValueError("no trustworthy public Telegram posts in snapshot")
    return list(events.values())


def parse_json_api(text, source, now=None):
    now = now or datetime.now(timezone.utc)
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("events", data.get("items"))
    if not isinstance(data, list):
        raise ValueError("JSON source must be a list or an object with events/items list")
    events = []
    for item in data[:100]:
        if not isinstance(item, dict):
            continue
        eid = item.get("id")
        title = item.get("title")
        if not isinstance(eid, (str, int)) or not isinstance(title, str):
            continue
        body = item.get("body", title)
        if not isinstance(body, str):
            continue
        link = item.get("url", source.url)
        if not isinstance(link, str):
            link = source.url
        kind = item.get("kind", "news")
        if kind not in ("news", "event", "patch_note", "announcement"):
            continue
        result = _event(source.world, source.id, str(eid), title, body, link, now, kind=kind)
        if result: events.append(result)
    if data and not events:
        raise ValueError("JSON feed entries unavailable after validation")
    return events


def parse_webpage(text, source, now=None):
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(text, "html.parser")
    selector = source.selector or "article, main"
    nodes = soup.select(selector, limit=10)
    if not nodes:
        # Misconfigured CSS and anti-bot/error pages must be retried rather
        # than marking a live source's warmup as successful with no posts.
        raise ValueError("webpage selector not present")
    events = []
    for index, node in enumerate(nodes):
        body = _plain(str(node))
        if not body or len(body) < 30:
            continue
        title_node = node.select_one("h1, h2, h3")
        title = title_node.get_text(" ", strip=True) if title_node else "Website update"
        fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]
        result = _event(source.world, source.id, f"{index}:{fingerprint}", title, body, source.url, now, kind="patch_note")
        if result: events.append(result)
    if not events:
        raise ValueError("webpage content unavailable after validation")
    return events


def parse_scryde_forum(text, source, now=None):
    """Read-only official public XenForo thread parser with stable post IDs.

    Does not fetch latest or follow redirects. A fixed page can become stale:
    the administrator must update its URL after verifying a new public page.
    """
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(text, "html.parser")
    nodes = soup.select("article.message")
    if not nodes:
        # Empty/error/challenge pages must not be treated as a valid event
        # snapshot and must never generate a synthetic cancellation.
        raise ValueError("public forum post elements unavailable")
    by_post = {}
    duplicate = set()
    for article in nodes[:120]:
        attr = article.get("data-content") or article.get("id") or ""
        match = re.search(r"post-?([0-9]+)", str(attr))
        if not match:
            continue
        raw_id = match.group(1)
        if len(raw_id) > 12 or not raw_id.isascii() or not raw_id.isdecimal():
            continue
        post_id = int(raw_id)
        if post_id <= 0:
            continue
        content = article.select_one("div.bbWrapper")
        if content is None:
            continue
        body = _plain(str(content))
        if not body:
            continue
        if post_id in by_post:
            duplicate.add(post_id)
            continue
        by_post[post_id] = body
    if not by_post:
        raise ValueError("public forum post identifiers unavailable")
    events = []
    for post_id, body in sorted(by_post.items()):
        if post_id in duplicate:
            # Conflicting/duplicate post IDs cannot safely select one article
            # as the canonical event.
            continue
        event = _event(
            source.world, source.id, f"forum-post:{post_id}",
            body[:100], body,
            source.url.rstrip("/") + f"#post-{post_id}", now,
        )
        if event:
            events.append(event)
    if not events:
        raise ValueError("no trustworthy public forum messages in snapshot")
    return events


PARSERS = {
    "rss": parse_rss,
    "telegram_public": parse_telegram_public,
    "scryde_forum": parse_scryde_forum,
    "json_api": parse_json_api,
    "webpage": parse_webpage,
}
