"""Persistent public-source backoff; pure stdlib, no real HTTP."""
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest

from community.source_health import SourceHealth, health_key
from community.state import DeliveryState

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
URL="https://example.com/feed"


class SourceHealthTests(unittest.TestCase):
    def test_initially_ready_and_exponential_backoff_is_capped(self):
        state=DeliveryState()
        health=SourceHealth(state)
        self.assertTrue(health.ready(URL,NOW))
        at=NOW
        delays=[20,40,80,120,120,120]
        for delay in delays:
            self.assertEqual(delay,health.fail(URL,at))
            self.assertFalse(health.ready(URL,at+timedelta(minutes=delay-1)))
            self.assertTrue(health.ready(URL,at+timedelta(minutes=delay)))
            at+=timedelta(minutes=delay)
        self.assertEqual(1,len(state.cursors))
        self.assertNotIn("example.com",str(state.cursors))
        self.assertNotIn("/feed",str(state.cursors))

    def test_backoff_persists_across_json_save_and_load(self):
        state=DeliveryState()
        health=SourceHealth(state)
        health.fail(URL,NOW)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"state.json"
            state.save(path)
            restored=DeliveryState.load(path)
            self.assertFalse(SourceHealth(restored).ready(URL,NOW+timedelta(minutes=10)))
            self.assertTrue(SourceHealth(restored).ready(URL,NOW+timedelta(minutes=20)))
            self.assertNotIn(URL,path.read_text())

    def test_recovery_clears_only_own_source(self):
        state=DeliveryState()
        health=SourceHealth(state)
        second="https://another.example.com/feed"
        health.fail(URL,NOW)
        health.fail(second,NOW)
        health.recover(URL)
        self.assertTrue(health.ready(URL,NOW))
        self.assertFalse(health.ready(second,NOW))
        self.assertNotIn(health_key(URL),state.cursors)

    def test_corrupt_or_unbounded_future_is_ignored_safely(self):
        state=DeliveryState()
        health=SourceHealth(state)
        state.cursors[health_key(URL)]="invalid-json"
        self.assertTrue(health.ready(URL,NOW))
        state.cursors[health_key(URL)]='{"failures":5,"retry_after":9999999999}'
        self.assertTrue(health.ready(URL,NOW))
        state.cursors[health_key(URL)]='{"failures":true,"retry_after":9999999999}'
        self.assertTrue(health.ready(URL,NOW))

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            SourceHealth(DeliveryState()).ready(URL,datetime(2026,11,17))


if __name__ == "__main__":
    unittest.main()
