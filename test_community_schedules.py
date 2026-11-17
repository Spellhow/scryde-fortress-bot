"""Offline schedule configuration, explicit provenance, time windows and replay."""
import unittest
from datetime import datetime, timezone, timedelta

from community.config import parse_config
from community.schedules import due_reminders
from community.models import Provenance, World
from community.state import DeliveryState

WORLD = {"network": "L2Dex", "name": "New-Interlude x25", "chronicle": "Interlude"}
START = datetime(2026, 12, 1, 20, 0, tzinfo=timezone.utc)


def config(**overrides):
    event = {
        "id": "clan-meeting-dec01",
        "world": WORLD,
        "title": "Clan meeting",
        "body": "Join the clan voice channel",
        "starts_at": START.isoformat(),
        "remind_before_minutes": [60, 15],
        "clan": "ClanA",
    }
    event.update(overrides)
    return {
        "version": 1, "sources": [],
        "scheduled_events": [event],
        "destinations": [{"id": "clan", "kind": "telegram", "address_env": "TG_CHAT", "token_env": "TG_TOKEN"}],
        "subscriptions": [{
            "destination_id": "clan", "world": WORLD,
            "source_ids": ["manual_schedule"], "event_types": ["event_reminder"],
            "clans": ["ClanA"],
        }],
    }


class ScheduleTests(unittest.TestCase):
    def test_schedule_without_remote_source_is_valid(self):
        conf = parse_config(config())
        self.assertEqual(0, len(conf.sources))
        self.assertEqual(1, len(conf.schedules))
        self.assertTrue(conf.subscriptions[0].matches(
            due_reminders(conf.schedules, START - timedelta(minutes=59))[0]
        ))

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            parse_config(config(starts_at="2026-12-01T20:00:00"))

    def test_invalid_offset_and_date(self):
        with self.assertRaises(ValueError):
            parse_config(config(starts_at="not-a-date"))

    def test_duplicate_lead_times_rejected(self):
        with self.assertRaises(ValueError):
            parse_config(config(remind_before_minutes=[60, 60]))

    def test_negative_lead_rejected(self):
        with self.assertRaises(ValueError):
            parse_config(config(remind_before_minutes=[-1]))

    def test_invalid_disabled_flag_rejected(self):
        with self.assertRaises(ValueError):
            parse_config(config(enabled="false"))

    def test_window_opens_when_expected(self):
        entry = parse_config(config()).schedules
        self.assertEqual([], due_reminders(entry, START - timedelta(minutes=61)))
        self.assertEqual(1, len(due_reminders(entry, START - timedelta(minutes=60))))
        self.assertEqual(1, len(due_reminders(entry, START - timedelta(minutes=41))))
        self.assertEqual([], due_reminders(entry, START - timedelta(minutes=40)))
        self.assertEqual(1, len(due_reminders(entry, START - timedelta(minutes=15))))
        self.assertEqual([], due_reminders(entry, START))
        self.assertEqual([], due_reminders(entry, START + timedelta(minutes=30)))

    def test_manual_provenance_and_explicit_time(self):
        entry = parse_config(config()).schedules
        event = due_reminders(entry, START - timedelta(minutes=60))[0]
        self.assertEqual(Provenance.MANUAL, event.provenance)
        self.assertEqual(START, event.occurs_at)
        self.assertIn("Manually scheduled", event.body)
        self.assertEqual("event_reminder", event.kind)

    def test_manual_reminder_render_has_no_fake_official_source(self):
        from community.publishers import render_plain_event
        entry = parse_config(config()).schedules
        event = due_reminders(entry, START - timedelta(minutes=60))[0]
        rendered = render_plain_event(event, 1900)
        self.assertIn("Manually scheduled", rendered)
        self.assertNotIn("https://github.com/", rendered)

    def test_disabled_event_does_not_trigger(self):
        entries = parse_config(config(enabled=False)).schedules
        self.assertEqual([], due_reminders(entries, START - timedelta(minutes=60)))

    def test_distinct_reminders_have_unique_event_ids(self):
        entries = parse_config(config()).schedules
        early = due_reminders(entries, START - timedelta(minutes=60))[0]
        later = due_reminders(entries, START - timedelta(minutes=15))[0]
        self.assertNotEqual(early.event_id, later.event_id)

    def test_duplicate_schedule_ids_in_same_world_rejected(self):
        conf = config()
        conf["scheduled_events"].append(dict(conf["scheduled_events"][0]))
        with self.assertRaises(ValueError):
            parse_config(conf)

    def test_unknown_source_and_world_rejected(self):
        conf = config()
        conf["subscriptions"][0]["source_ids"] = ["another-source"]
        with self.assertRaises(ValueError):
            parse_config(conf)

    def test_varying_timezones_are_compared_by_instant(self):
        local = START.astimezone(timezone(timedelta(hours=2)))
        conf = parse_config(config(starts_at=local.isoformat()))
        event = due_reminders(conf.schedules, START - timedelta(minutes=60))[0]
        self.assertEqual(event.occurs_at, START)


if __name__ == "__main__":
    unittest.main()
