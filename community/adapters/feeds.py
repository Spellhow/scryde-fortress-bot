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


def _plain(value, limit=3200):
    soup = BeautifulSoup(value or "", "html.parser")
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()
    return soup.get_text(" ", strip=True)[:limit]


def _event(world, source_id, external_id, title, body, link, now, kind="news"):
    if not title.strip() or not body.strip():
        return None
    return Event(world=world, source_id=source_id, external_id=external_id,
                 kind=kind, title=title[:160], body=body[:3200],
                 source_url=link, provenance=Provenance.OBSERVED, observed_at=now)


def parse_rss(text, source, now=None):
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("RSS external entities are forbidden")
    now = now or datetime.now(timezone.utc)
    root = ET.fromstring(text)
    events = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        body = _plain(item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or title)
        link = (item.findtext("link") or source.url).strip()
        eid = (item.findtext("guid") or link or title).strip()
        result = _event(source.world, source.id, eid, title, body, link, now)
        if result: events.append(result)
    namespace = "{http://www.w3.org/2005/Atom}"
    for entry in root.findall(f".//{namespace}entry"):
        title = (entry.findtext(f"{namespace}title") or "").strip()
        body = _plain(entry.findtext(f"{namespace}summary") or entry.findtext(f"{namespace}content") or title)
        link_element = entry.find(f"{namespace}link")
        link = link_element.get("href") if link_element is not None else source.url
        eid = entry.findtext(f"{namespace}id") or link or title
        result = _event(source.world, source.id, eid, title, body, link, now)
        if result: events.append(result)
    return events


def parse_telegram_public(text, source, now=None):
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(text, "html.parser")
    events = []
    for node in soup.select(".tgme_widget_message[data-post]"):
        eid = node.get("data-post", "").strip()
        content = node.select_one(".tgme_widget_message_text")
        if not eid or content is None:
            continue
        body = _plain(str(content))
        if not body:
            continue
        link_node = node.select_one(".tgme_widget_message_date")
        link = link_node.get("href") if link_node and link_node.get("href") else source.url
        result = _event(source.world, source.id, eid, body[:100], body, link, now)
        if result: events.append(result)
    return events


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
    return events


def parse_webpage(text, source, now=None):
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(text, "html.parser")
    selector = source.selector or "article, main"
    nodes = soup.select(selector, limit=10)
    if not nodes:
        return []
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
    return events


PARSERS = {
    "rss": parse_rss,
    "telegram_public": parse_telegram_public,
    "json_api": parse_json_api,
    "webpage": parse_webpage,
}
