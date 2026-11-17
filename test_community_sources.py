"""Offline config, parser, SSRF, and delivery checks."""
import json
import socket
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from community.config import parse_config, credential_environment
from community.fetch import FetchError, resolve_public_https
from community.adapters.feeds import parse_rss, parse_telegram_public, parse_json_api, parse_webpage
from community.models import Event, Provenance, World, Destination
from community.publishers import send_event

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
WORLD = {"network": "Scryde", "name": "x1000"}


def source(kind="rss", url="https://example.com/feed"):
    from community.config import SourceConfig
    return SourceConfig("s", kind, World("Scryde", "x1000"), url)


class SourceTests(unittest.TestCase):
    def test_config_accepts_example(self):
        from pathlib import Path
        conf = parse_config(json.loads((Path(__file__).parent/"community.example.json").read_text()))
        self.assertEqual(2, len(conf.sources))
        self.assertEqual({"scryde-official-news", "l2dex-new-interlude-castles"}, {s.id for s in conf.sources})
        self.assertTrue(all(not s.enabled for s in conf.sources))
        self.assertEqual("clan-telegram", conf.subscriptions[0].destination_id)

    def test_reject_duplicate_sources(self):
        base = {"version": 1, "sources": [
            {"id": "a", "kind": "rss", "url": "https://example.com", "world": WORLD},
            {"id": "a", "kind": "rss", "url": "https://example.com", "world": WORLD}],
            "destinations": [], "subscriptions": []}
        with self.assertRaises(ValueError):
            parse_config(base)

    def test_no_private_telegram_channel(self):
        with self.assertRaises(ValueError):
            source("telegram_public", "https://t.me/private_channel")

    def test_reject_http_and_credentials(self):
        for url in ("http://example.com", "https://me:password@example.com/data",
                    "https://127.0.0.1:8080"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                source("rss", url)

    def test_reject_bad_config_flags(self):
        base = {"version": 1, "sources": [
            {"id":"x","kind":"rss","url":"https://example.com","world":WORLD,
             "enabled":"false"}], "destinations":[], "subscriptions":[]}
        with self.assertRaises(ValueError):
            parse_config(base)

    def test_json_feed_rejects_unsafe_links(self):
        rows = parse_json_api(
            '{"events":[{"id":"42","title":"Update","body":"Test","url":"javascript:alert(1)"}]}',
            source("json_api"), NOW)
        self.assertEqual([], rows)

    def test_secret_map_is_never_sourced_from_config(self):
        env = credential_environment({"COMMUNITY_SECRETS_JSON": '{"TG_CHAT":"-123","TG_TOKEN":"secret"}'})
        self.assertEqual("-123", env["TG_CHAT"])
        with self.assertRaises(ValueError):
            credential_environment({"COMMUNITY_SECRETS_JSON": '["secret"]'})

    @patch("community.fetch.socket.getaddrinfo")
    def test_dns_rejects_private_addresses(self, lookup):
        lookup.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with self.assertRaises(FetchError):
            resolve_public_https("https://example.com/")

    @patch("community.fetch.socket.getaddrinfo")
    def test_dns_rejects_mixed_public_private(self, lookup):
        lookup.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ]
        with self.assertRaises(FetchError):
            resolve_public_https("https://example.com/")

    def test_rss(self):
        xml = "<rss><channel><item><guid>post-1</guid><title>Update</title><description>Patch details</description><link>https://example.com/post</link></item></channel></rss>"
        events = parse_rss(xml, source(), NOW)
        self.assertEqual(1, len(events))
        self.assertEqual("post-1", events[0].external_id)

    def test_atom(self):
        xml = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:1</id><title>News</title><summary>Body</summary><link href="https://example.com/p"/></entry></feed>'
        self.assertEqual("tag:1", parse_rss(xml, source(), NOW)[0].external_id)

    def test_xml_rejects_doctype(self):
        with self.assertRaises(ValueError):
            parse_rss("<!DOCTYPE foo><rss/>", source(), NOW)

    def test_telegram_public(self):
        html = '<div class="tgme_widget_message" data-post="scryde/42"><div class="tgme_widget_message_text">Siege tonight</div><a class="tgme_widget_message_date" href="https://t.me/scryde/42">date</a></div>'
        rows = parse_telegram_public(html, source("telegram_public", "https://t.me/s/scryde"), NOW)
        self.assertEqual("scryde/42", rows[0].external_id)

    def test_json_feed(self):
        events = parse_json_api('{"events":[{"id":"p42","title":"New event","body":"Details"}]}', source("json_api"), NOW)
        self.assertEqual(1, len(events))
        self.assertEqual("news", events[0].kind)

    def test_webpage_changes_generate_new_id(self):
        first = parse_webpage('<main><h1>Patch</h1><p>Many adjustments to all classes and spells.</p></main>', source("webpage"), NOW)
        second = parse_webpage('<main><h1>Patch</h1><p>Many different adjustments to all classes.</p></main>', source("webpage"), NOW)
        self.assertNotEqual(first[0].event_id, second[0].event_id)

    def test_telegram_publisher_uses_secret_and_handles_failure(self):
        e = Event(World("Scryde","x1000"),"s","1","news","title","body",
                  "https://example.com",Provenance.OBSERVED,NOW)
        d = Destination("a", "telegram", "CHAT_ID", "BOT_TOKEN")
        calls = []
        def fake(url, payload):
            calls.append((url, payload))
            return (200, b'{"ok":true,"result":{"message_id":42}}')
        self.assertTrue(send_event(d, e, "uk", {"CHAT_ID":"123","BOT_TOKEN":"secret"},fake))
        self.assertIn("secret", calls[0][0])
        self.assertEqual("123", calls[0][1]["chat_id"])
        self.assertFalse(send_event(d, e, "uk", {"CHAT_ID":"123","BOT_TOKEN":"secret"},
                                   lambda *_: (401,b'{"ok":false}')))

    def test_discord_publisher_has_no_mentions(self):
        e = Event(World("Scryde","x1000"),"s","1","news","title","@everyone",
                  "https://example.com",Provenance.OBSERVED,NOW)
        d = Destination("discord", "discord", "WEBHOOK")
        calls=[]
        def fake(url, payload):
            calls.append((url, payload))
            return (200, b'{"id":"123"}')
        address = "https://discord.com/api/webhooks/1/secrethere"
        self.assertTrue(send_event(d,e,"en",{"WEBHOOK":address},fake))
        self.assertEqual([],calls[0][1]["allowed_mentions"]["parse"])
        self.assertFalse(send_event(d,e,"en",{"WEBHOOK":"https://evil.example/api/webhooks/1/x"},fake))


if __name__ == "__main__":
    unittest.main()
