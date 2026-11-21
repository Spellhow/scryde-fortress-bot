"""Untrusted public RSS/Atom/JSON duplicate article IDs must not publish arbitrary content."""
from datetime import datetime, timedelta, timezone
import json
import unittest

from community.adapters.feeds import parse_rss, parse_json_api
from community.config import SourceConfig, parse_config
from community.models import World
from community.runner import run
from community.source_health import health_key, parser_identity
from community.state import DeliveryState

NOW = datetime(2026, 11, 21, 11, tzinfo=timezone.utc)
WORLD = World("Lineage", "Interlude")


def source(kind="rss"):
    return SourceConfig("feed", kind, WORLD, "https://example.org/feed")


def item(eid, title):
    return (
        "<item><guid>{}</guid><title>{}</title>"
        "<description>Public update</description><link>https://example.org/post/{}</link></item>"
    ).format(eid, title, eid)


def rss(*items):
    return "<rss><channel>{}</channel></rss>".format("".join(items))


def atom(*entries):
    pieces = []
    for eid, title in entries:
        pieces.append(
            '<entry><id>tag:example.org,{}</id><title>{}</title>'
            '<summary>Public update</summary>'
            '<link href="https://example.org/post/{}"/></entry>'.format(
                eid, title, eid
            )
        )
    return '<feed xmlns="http://www.w3.org/2005/Atom">{}</feed>'.format(
        "".join(pieces)
    )


def json_feed(*entries):
    return json.dumps({"events": [
        {"id": eid, "title": title, "body": "Public update",
         "url": "https://example.org/post/{}".format(eid)}
        for eid, title in entries
    ]})


def config(kind):
    world = {"network": WORLD.network, "name": WORLD.name}
    return parse_config({
        "version": 1,
        "sources": [{"id": "feed", "kind": kind, "url": "https://example.org/feed",
                     "world": world}],
        "destinations": [{"id": "t", "kind": "telegram",
                          "address_env": "CHAT", "token_env": "TOKEN"}],
        "subscriptions": [{"destination_id": "t", "world": world, "source_ids": ["feed"]}],
    })


class DuplicateSourceEventIdsTests(unittest.TestCase):
    def test_duplicate_rss_guid_quarantined_both_versions(self):
        for items in (
            (item("same", "Version A"), item("same", "Version B")),
            (item("same", "Version B"), item("same", "Version A")),
        ):
            with self.subTest(items=items), self.assertRaises(ValueError):
                parse_rss(rss(*items), source(), NOW)

    def test_distinct_rss_news_survives_conflicting_guid(self):
        entries = (item("same", "Version A"), item("unique", "Verified"),
                   item("same", "Version B"))
        events = parse_rss(rss(*entries), source(), NOW)
        self.assertEqual(["unique"], [event.external_id for event in events])
        self.assertEqual("Verified", events[0].title)

    def test_atom_ids_quarantined_without_hiding_unrelated_entries(self):
        with self.assertRaises(ValueError):
            parse_rss(atom(("same", "A"), ("same", "B")), source(), NOW)
        events = parse_rss(atom(("same", "A"), ("other", "Unique"), ("same", "B")),
                           source(), NOW)
        self.assertEqual(["tag:example.org,other"], [event.external_id for event in events])

    def test_json_duplicate_ids_quarantined_with_same_event_kind(self):
        with self.assertRaises(ValueError):
            parse_json_api(json_feed(("same", "A"), ("same", "B")),
                           source("json_api"), NOW)
        events = parse_json_api(json_feed(("same", "A"), ("unique", "Unique"),
                                          ("same", "B")), source("json_api"), NOW)
        self.assertEqual(["unique"], [event.external_id for event in events])

    def test_different_event_kinds_still_have_distinct_normalized_ids(self):
        payload = json.dumps({"events": [
            {"id": "same", "title": "News", "kind": "news"},
            {"id": "same", "title": "Event", "kind": "event"},
        ]})
        events = parse_json_api(payload, source("json_api"), NOW)
        self.assertEqual({"news", "event"}, {event.kind for event in events})
        self.assertEqual(2, len({event.event_id for event in events}))

    def test_invalid_duplicate_baseline_does_not_warm_and_recovers(self):
        cfg = config("rss")
        state = DeliveryState()
        bad = rss(item("same", "A"), item("same", "B"))
        failed = run(cfg, state, fetch=lambda _: bad,
                     send=lambda *_: self.fail("bad source must not send"),
                     credentials={}, now=NOW)
        self.assertEqual(1, len(failed.errors))
        self.assertEqual(0, failed.subscriptions_initialized)
        marker = health_key(parser_identity(cfg.sources[0]))
        self.assertIn(marker, state.cursors)
        retried = run(cfg, state, fetch=lambda _: rss(item("same", "A")),
                      send=lambda *_: self.fail("must be in cooldown"),
                      credentials={}, now=NOW + timedelta(minutes=5))
        self.assertEqual(1, retried.deferred_sources)
        baseline = run(cfg, state, fetch=lambda _: rss(item("same", "A")),
                       send=lambda *_: self.fail("first valid snapshot is silent"),
                       credentials={}, now=NOW + timedelta(minutes=20))
        self.assertEqual(1, baseline.subscriptions_initialized)
        self.assertNotIn(marker, state.cursors)
        delivered = []
        next_run = run(cfg, state,
                       fetch=lambda _: rss(item("same", "A"), item("new", "New")),
                       send=lambda dest, event, lang, cred: delivered.append(
                           event.external_id) or True,
                       credentials={}, now=NOW + timedelta(minutes=40))
        self.assertEqual(1, next_run.sent)
        self.assertEqual(["new"], delivered)

    def test_partial_conflict_does_not_ack_missing_article_and_replays(self):
        cfg = config("json_api")
        state = DeliveryState()
        run(cfg, state, fetch=lambda _: json_feed(("old", "Original")),
            send=lambda *_: self.fail("baseline silent"), credentials={}, now=NOW)
        calls = []
        mixed = json_feed(("old", "Original"), ("same", "Version A"),
                          ("unrelated", "Valid"), ("same", "Version B"))
        result = run(cfg, state, fetch=lambda _: mixed,
                     send=lambda dest, event, lang, cred: calls.append(
                         event.external_id) or True,
                     credentials={}, now=NOW + timedelta(minutes=1))
        self.assertEqual(1, result.sent)
        self.assertEqual(["unrelated"], calls)
        calls.clear()
        recovered = json_feed(("old", "Original"), ("same", "Resolved"),
                              ("unrelated", "Valid"))
        result = run(cfg, state, fetch=lambda _: recovered,
                     send=lambda dest, event, lang, cred: calls.append(
                         event.external_id) or True,
                     credentials={}, now=NOW + timedelta(minutes=21))
        self.assertEqual(1, result.sent)
        self.assertEqual(["same"], calls)
        self.assertEqual(0, len(result.errors))


if __name__ == "__main__":
    unittest.main()
