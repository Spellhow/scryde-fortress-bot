"""Stable public HTML article identity and safe old receipt migration."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from community.adapters.feeds import MAX_WEBPAGE_NODES, parse_webpage
from community.config import SourceConfig, parse_config
from community.models import World
from community.runner import _init_key, run
from community.state import DeliveryState

NOW = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
WORLD = World("Lineage", "Interlude")
SOURCE = SourceConfig("site", "webpage", WORLD, "https://example.org/news")

def html(title):
    return (
        "<article><h2>{}</h2><p>"
        "Long published update with enough details for public readers."
        "</p></article>"
    ).format(title)

A, B, C = html("First patch"), html("Second patch"), html("Third patch")

def parse(text):
    return parse_webpage(text, SOURCE, NOW)

def config():
    world = {"network": WORLD.network, "name": WORLD.name}
    return parse_config({
        "version": 1,
        "sources": [{"id": "site", "kind": "webpage",
                     "url": SOURCE.url, "world": world}],
        "destinations": [
            {"id": "telegram", "kind": "telegram",
             "address_env": "CHAT", "token_env": "TOKEN"},
            {"id": "discord", "kind": "discord",
             "address_env": "WEBHOOK"},
        ],
        "subscriptions": [
            {"destination_id": alias, "world": world, "source_ids": ["site"]}
            for alias in ("telegram", "discord")
        ],
    })

def legacy_event(event, index):
    fingerprint = event.external_id.split(":", 1)[1]
    return replace(event, external_id="{}:{}".format(index, fingerprint))


class StableWebpageIdTests(unittest.TestCase):
    def test_reordering_posts_does_not_change_event_ids(self):
        before = parse(A + B)
        after = parse(B + A)
        self.assertEqual(
            {e.event_id for e in before}, {e.event_id for e in after}
        )
        self.assertTrue(all(e.external_id.startswith("content:") for e in after))

    def test_adding_new_post_only_changes_new_event_identity(self):
        before = parse(A + B)
        after = parse(C + A + B)
        old = {e.event_id for e in before}
        self.assertTrue(old.issubset({e.event_id for e in after}))
        self.assertEqual(1, len({e.event_id for e in after} - old))

    def test_duplicate_identical_page_nodes_are_one_event(self):
        self.assertEqual(1, len(parse(A + A)))
        self.assertEqual(2, len(parse(A + B + A)))

    def test_ordinary_warm_start_reorder_then_one_new_post(self):
        cfg = config()
        state = DeliveryState()
        run(cfg, state, fetch=lambda _: A + B,
            send=lambda *_: self.fail("warm baseline is silent"),
            credentials={}, now=NOW)
        attempts = []
        second = run(cfg, state, fetch=lambda _: B + A,
                     send=lambda dest, event, *_: attempts.append(
                         (dest.id, event.title)) or True,
                     credentials={}, now=NOW + timedelta(minutes=20))
        self.assertEqual(0, second.sent)
        self.assertEqual([], attempts)
        third = run(cfg, state, fetch=lambda _: C + B + A,
                    send=lambda dest, event, *_: attempts.append(
                        (dest.id, event.title)) or True,
                    credentials={}, now=NOW + timedelta(minutes=40))
        self.assertEqual(2, third.sent)
        self.assertEqual(
            [("telegram", "Third patch"), ("discord", "Third patch")],
            attempts
        )

    def test_legacy_position_receipts_migrate_across_reordered_articles(self):
        cfg = config()
        state = DeliveryState()
        old = parse(A + B)
        # Simulate existing stored v1 acknowledgements produced by the old
        # position:hash HTML adapter. No direct state schema changes.
        for sub in cfg.subscriptions:
            state.cursors[_init_key(cfg.sources[0], sub)] = "initialized"
            for index, event in enumerate(old):
                state.mark_delivered(sub.destination_id,
                                     legacy_event(event, index).event_id, 12345)
        calls = []
        outcome = run(cfg, state, fetch=lambda _: C + B + A,
                      send=lambda dest, event, *_: calls.append(
                          (dest.id, event.title)) or True,
                      credentials={}, now=NOW)
        self.assertEqual(2, outcome.sent)
        self.assertEqual(
            [("telegram", "Third patch"), ("discord", "Third patch")],
            calls,
        )
        for event in old:
            for sub in cfg.subscriptions:
                self.assertTrue(state.was_delivered(sub.destination_id, event.event_id))
        calls.clear()
        second = run(cfg, state, fetch=lambda _: A + C + B,
                     send=lambda *args: calls.append(args) or True,
                     credentials={}, now=NOW + timedelta(minutes=20))
        self.assertEqual(0, second.sent)
        self.assertFalse(calls)

    def test_unacknowledged_legacy_destination_still_retries(self):
        cfg = config()
        state = DeliveryState()
        event = parse(A)[0]
        for sub in cfg.subscriptions:
            state.cursors[_init_key(cfg.sources[0], sub)] = "initialized"
        state.mark_delivered("telegram", legacy_event(event, 0).event_id, 12345)
        attempts = []
        outcome = run(cfg, state, fetch=lambda _: A,
                      send=lambda dest, event, *_: attempts.append(dest.id) or True,
                      credentials={}, now=NOW)
        self.assertEqual(1, outcome.sent)
        self.assertEqual(["discord"], attempts)
        self.assertTrue(state.was_delivered("telegram", event.event_id))
        self.assertTrue(state.was_delivered("discord", event.event_id))

    def test_legacy_tenth_position_receipt_supported(self):
        self.assertEqual(10, MAX_WEBPAGE_NODES)
        event = parse(A)[0]
        cfg = config()
        state = DeliveryState()
        for sub in cfg.subscriptions:
            state.cursors[_init_key(cfg.sources[0], sub)] = "initialized"
            state.mark_delivered(sub.destination_id,
                                 legacy_event(event, MAX_WEBPAGE_NODES - 1).event_id,
                                 12345)
        attempts = []
        result = run(cfg, state, fetch=lambda _: A,
                     send=lambda *args: attempts.append(args) or True,
                     credentials={}, now=NOW)
        self.assertEqual(0, result.sent)
        self.assertFalse(attempts)

    def test_dry_run_never_migrates_receipts(self):
        cfg = config()
        state = DeliveryState()
        event = parse(A)[0]
        for sub in cfg.subscriptions:
            state.cursors[_init_key(cfg.sources[0], sub)] = "initialized"
            state.mark_delivered(sub.destination_id,
                                 legacy_event(event, 0).event_id, 12345)
        before = (dict(state.cursors), dict(state.delivered))
        outcome = run(cfg, state, fetch=lambda _: A,
                      send=lambda *_: self.fail("dry-run is silent"),
                      credentials={}, now=NOW, dry_run=True)
        self.assertEqual(0, outcome.sent)
        self.assertEqual(before, (state.cursors, state.delivered))


if __name__ == "__main__":
    unittest.main()
