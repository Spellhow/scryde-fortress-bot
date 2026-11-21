"""Fail closed on populated sources whose articles are all unusable.

No external feeds, Telegram/Discord messages or paid models are contacted.
"""
from datetime import datetime, timedelta, timezone
import json
import unittest

from community.adapters.feeds import parse_json_api, parse_rss, parse_webpage
from community.config import SourceConfig, parse_config
from community.models import World
from community.runner import _init_key, run
from community.source_health import health_key, parser_identity
from community.state import DeliveryState

NOW = datetime(2026, 11, 21, 8, tzinfo=timezone.utc)
WORLD = World("Lineage", "Interlude")
SOURCES = {
    "rss": SourceConfig("news", "rss", WORLD, "https://example.org/feed"),
    "json_api": SourceConfig("news", "json_api", WORLD, "https://example.org/feed"),
    "webpage": SourceConfig("news", "webpage", WORLD, "https://example.org/feed"),
}

RSS_BAD = """<rss><channel>
    <item><guid>1</guid><title>Patch</title>
    <link>javascript:alert(1)</link></item>
    </channel></rss>"""
RSS_VALID = """<rss><channel>
    <item><guid>1</guid><title>Patch</title><description>Updated classes</description>
    <link>https://example.org/post/1</link></item>
    </channel></rss>"""
RSS_NEXT = RSS_VALID.replace("</channel>", """<item><guid>2</guid>
    <title>Next patch</title><description>Many more changes</description>
    <link>https://example.org/post/2</link></item></channel>""")
JSON_BAD = json.dumps({"events": [
    {"id": "1", "title": "Patch", "url": "https://example.org/post?api_key=secret"},
    {"id": "2", "title": 42},
]})
JSON_VALID = json.dumps({"events": [
    {"id": "1", "title": "Patch", "body": "Updated classes", "url": "https://example.org/post/1"}
]})
JSON_NEXT = json.dumps({"events": [
    {"id": "1", "title": "Patch", "body": "Updated classes", "url": "https://example.org/post/1"},
    {"id": "2", "title": "More", "body": "Many more changes", "url": "https://example.org/post/2"}
]})
WEB_BAD = "<main><h1>Patch</h1><p>Oops</p></main>"
WEB_VALID = "<main><h1>Patch</h1><p>Updated classes with extensive new adjustments.</p></main>"
WEB_NEXT = WEB_VALID + "<article><h2>Second patch</h2><p>New adjustments for the community and all classes.</p></article>"
CASES = {
    "rss": (RSS_BAD, RSS_VALID, RSS_NEXT, parse_rss),
    "json_api": (JSON_BAD, JSON_VALID, JSON_NEXT, parse_json_api),
    "webpage": (WEB_BAD, WEB_VALID, WEB_NEXT, parse_webpage),
}


def config(kind):
    world = {"network": WORLD.network, "name": WORLD.name}
    return parse_config({
        "version": 1,
        "sources": [{"id": "news", "kind": kind, "url": "https://example.org/feed", "world": world}],
        "destinations": [{"id": "channel", "kind": "telegram", "address_env": "CHAT", "token_env": "TOKEN"}],
        "subscriptions": [{"destination_id": "channel", "world": world, "source_ids": ["news"]}],
    })


class NonemptyFeedValidationTests(unittest.TestCase):
    def test_nonempty_rss_atom_json_and_html_cannot_be_empty_success(self):
        for kind, (bad, _, _, parser) in CASES.items():
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                parser(bad, SOURCES[kind], NOW)
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom">'
                '<entry><id>tag:1</id><title>Patch</title>'
                '<link href="https://example.org/?token=secret" /></entry></feed>')
        with self.assertRaises(ValueError):
            parse_rss(atom, SOURCES["rss"], NOW)

    def test_genuinely_empty_rss_atom_and_json_remain_valid(self):
        self.assertEqual([], parse_rss("<rss><channel/></rss>", SOURCES["rss"], NOW))
        self.assertEqual([], parse_rss(
            '<feed xmlns="http://www.w3.org/2005/Atom"></feed>', SOURCES["rss"], NOW))
        self.assertEqual([], parse_json_api('{"events":[]}', SOURCES["json_api"], NOW))
        self.assertEqual([], parse_json_api('[]', SOURCES["json_api"], NOW))

    def test_mixed_valid_invalid_articles_keep_only_trusted_items(self):
        # Build a small well-formed mixed source with one safe and one unsafe entry.
        mixed_rss = RSS_VALID.replace(
            "</channel>",
            '<item><guid>unsafe</guid><title>Bad</title><link>http://localhost/p</link></item></channel>')
        parsed = parse_rss(mixed_rss, SOURCES["rss"], NOW)
        self.assertEqual(["1"], [ev.external_id for ev in parsed])
        mixed_json = json.dumps({"events": [
            {"id": "bad", "title": "Bad", "url": "https://example.org/?token=secret"},
            {"id": "good", "title": "Good", "url": "https://example.org/post"},
        ]})
        self.assertEqual(
            ["good"], [e.external_id for e in parse_json_api(mixed_json, SOURCES["json_api"], NOW)])
        mixed_html = WEB_BAD + WEB_VALID
        self.assertEqual(1, len(parse_webpage(mixed_html, SOURCES["webpage"], NOW)))

    def test_first_invalid_snapshot_does_not_initialize_warmup(self):
        for kind, (bad, valid, next_page, _) in CASES.items():
            with self.subTest(kind=kind):
                cfg = config(kind)
                state = DeliveryState()
                first = run(cfg, state, fetch=lambda _: bad,
                            send=lambda *_: self.fail("bad snapshot cannot deliver"),
                            credentials={}, now=NOW)
                self.assertEqual(1, len(first.errors))
                self.assertEqual(0, first.subscriptions_initialized)
                marker = _init_key(cfg.sources[0], cfg.subscriptions[0])
                self.assertNotIn(marker, state.cursors)
                cooldown = health_key(parser_identity(cfg.sources[0]))
                self.assertIn(cooldown, state.cursors)
                delayed = run(cfg, state,
                              fetch=lambda _: self.fail("backoff should defer"),
                              send=lambda *_: self.fail("no send"),
                              credentials={}, now=NOW + timedelta(minutes=5))
                self.assertEqual(1, delayed.deferred_sources)
                baseline = run(cfg, state, fetch=lambda _: valid,
                               send=lambda *_: self.fail("first valid snapshot is silent"),
                               credentials={}, now=NOW + timedelta(minutes=20))
                self.assertEqual(0, len(baseline.errors))
                self.assertEqual(1, baseline.subscriptions_initialized)
                self.assertIn(marker, state.cursors)
                self.assertNotIn(cooldown, state.cursors)
                calls = []
                later = run(cfg, state, fetch=lambda _: next_page,
                            send=lambda dest, event, lang, creds: calls.append(event.external_id) or True,
                            credentials={}, now=NOW + timedelta(minutes=40))
                self.assertEqual(1, later.sent)
                self.assertEqual(1, len(calls))

    def test_existing_receipts_survive_invalid_snapshot_then_recovery(self):
        for kind, (_, valid, next_page, _) in CASES.items():
            with self.subTest(kind=kind):
                cfg = config(kind)
                state = DeliveryState()
                run(cfg, state, fetch=lambda _: valid,
                    send=lambda *_: self.fail("warm start is silent"),
                    credentials={}, now=NOW)
                # Baseline already acknowledged; a later bad response cannot erase it.
                previous = dict(state.delivered)
                bad = CASES[kind][0]
                result = run(cfg, state, fetch=lambda _: bad, send=lambda *_: True,
                             credentials={}, now=NOW + timedelta(minutes=1))
                self.assertEqual(1, len(result.errors))
                self.assertEqual(previous, state.delivered)
                calls = []
                result = run(cfg, state, fetch=lambda _: next_page,
                             send=lambda dest, event, lang, creds: calls.append(event.external_id) or True,
                             credentials={}, now=NOW + timedelta(minutes=21))
                self.assertEqual(1, result.sent)
                self.assertEqual(1, len(calls))


if __name__ == "__main__":
    unittest.main()
