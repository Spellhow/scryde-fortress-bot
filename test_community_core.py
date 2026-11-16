"""Offline regression for multiple worlds, destinations, and public state."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from community import World, Event, Provenance, Destination, Subscription, DeliveryState, dispatch_events
from community.adapters.scryde import ScrydeRankingAdapter

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def make_event(world, clan="BSOE", revision=""):
    return Event(world, "scryde", "siege-42", "siege_registration", "Siege", "A siege registered",
                 "https://example.invalid/siege", Provenance.OBSERVED, NOW, NOW,
                 clan=clan, object_name="Giran", revision=revision)


class CommunityCoreTests(unittest.TestCase):
    def setUp(self):
        self.world = World("Scryde", "x1000", "High Five")
        self.targets = {
            "alpha": Destination("alpha", "telegram", "CHAT_ALPHA", "TG_TOKEN"),
            "beta": Destination("beta", "discord", "DISCORD_WEBHOOK"),
        }
        self.subs = [
            Subscription("alpha", self.world, frozenset({"siege_registration"}), clans=frozenset({"BSOE"})),
            Subscription("beta", self.world, frozenset({"siege_registration"})),
        ]

    def test_world_identity_casefold(self):
        self.assertEqual(self.world.identity, World("scryde", "X1000", "high five").identity)

    def test_different_world_separate_event(self):
        self.assertNotEqual(make_event(self.world).event_id, make_event(World("Scryde", "x100")).event_id)

    def test_revision_keeps_event_id(self):
        original = make_event(self.world)
        revised = make_event(self.world, revision="changed")
        self.assertEqual(original.event_id, revised.event_id)
        self.assertNotEqual(original.fingerprint, revised.fingerprint)

    def test_provenance_required(self):
        with self.assertRaises(ValueError):
            Event(self.world, "src", "id", "news", "Title", "Body", "https://example.invalid",
                  "observed", NOW)

    def test_timezones_required(self):
        with self.assertRaises(ValueError):
            Event(self.world, "src", "id", "news", "Title", "Body", "https://example.invalid",
                  Provenance.OBSERVED, datetime(2026, 11, 16))

    def test_env_reference_validation(self):
        with self.assertRaises(ValueError):
            Destination("bad", "telegram", "-1000000", "TG_TOKEN")

    def test_fanout_and_replay_skip(self):
        state = DeliveryState()
        calls = []
        def send(dest, event, language):
            calls.append(dest.id)
            return True
        result = dispatch_events([make_event(self.world)], self.subs, self.targets, state, send, now=NOW)
        self.assertEqual((2, 2, 0), (result.attempted, result.sent, result.skipped))
        result2 = dispatch_events([make_event(self.world)], self.subs, self.targets, state, send, now=NOW)
        self.assertEqual((0, 0, 2), (result2.attempted, result2.sent, result2.skipped))
        self.assertEqual(["alpha", "beta"], calls)

    def test_failed_destination_does_not_block_other(self):
        state = DeliveryState()
        def send(dest, event, lang):
            if dest.id == "alpha":
                raise RuntimeError("secret-should-never-be-logged")
            return True
        result = dispatch_events([make_event(self.world)], self.subs, self.targets, state, send, now=NOW)
        self.assertEqual(1, result.sent)
        self.assertFalse(state.was_delivered("alpha", make_event(self.world).event_id))
        self.assertTrue(state.was_delivered("beta", make_event(self.world).event_id))
        self.assertNotIn("secret-should-never-be-logged", str(result.errors))

    def test_explicit_send_rejection_is_not_marked_delivered(self):
        state = DeliveryState()
        result = dispatch_events(
            [make_event(self.world)], self.subs, self.targets, state,
            lambda *_: False, now=NOW,
        )
        self.assertEqual(0, result.sent)
        self.assertEqual(2, len(result.errors))
        self.assertFalse(state.was_delivered("alpha", make_event(self.world).event_id))

    def test_unknown_destination_is_reported(self):
        state = DeliveryState()
        result = dispatch_events(
            [make_event(self.world)],
            [Subscription("missing", self.world)],
            self.targets, state, lambda *_: True, now=NOW,
        )
        self.assertEqual(0, result.sent)
        self.assertEqual(1, len(result.errors))

    def test_clan_filter_and_world_filter(self):
        state = DeliveryState()
        calls = []
        subs = self.subs + [Subscription("beta", World("Scryde", "x100"))]
        result = dispatch_events([make_event(self.world, clan="OTHER")], subs, self.targets, state,
                                 lambda dest,event,lang: calls.append(dest.id) or True, now=NOW)
        self.assertEqual(["beta"], calls)

    def test_state_roundtrip(self):
        state = DeliveryState()
        state.mark_delivered("alpha", make_event(self.world).event_id, 123456)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state.save(path)
            text = path.read_text()
            self.assertNotIn("CHAT_ALPHA", text)
            self.assertNotIn("TG_TOKEN", text)
            self.assertTrue(DeliveryState.load(path).was_delivered("alpha", make_event(self.world).event_id))

    def test_reject_unknown_schema(self):
        with self.assertRaises(ValueError):
            DeliveryState.from_dict({"schema_version": 99, "delivered": {}})

    def test_scryde_shadow_adapter_handles_invalid_rows(self):
        adapter = ScrydeRankingAdapter("ranking", "https://example.invalid")
        rows = [None, 3, {}, {"id": 116, "name": "Antharas", "owner": {"name": "BSOE"},
                "siege_at": 2000000000, "siege_sides": {"attackers": [{"name": "ENEMY"}]}}]
        events = adapter.parse(rows, world=self.world)
        self.assertEqual(1, len(events))
        self.assertEqual("Antharas", events[0].object_name)
        self.assertEqual(Provenance.OBSERVED, events[0].provenance)


if __name__ == "__main__":
    unittest.main()
