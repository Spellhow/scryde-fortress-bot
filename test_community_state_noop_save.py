"""Durable no-op GitHub-only state writes: no disk churn or extra commits."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from community.state import DeliveryState


class StateNoopWriteTests(unittest.TestCase):
    def test_second_identical_save_skips_replace_and_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"state.json"
            state=DeliveryState()
            state.mark_delivered("alpha","event-1",12345)
            state.cursors["warm:abc"]="initialized"
            self.assertTrue(state.save(target))
            first=target.read_bytes()
            stamp=target.stat().st_mtime_ns
            with patch("community.state.tempfile.mkstemp",
                       side_effect=AssertionError("unneeded temp file")), \
                 patch("community.state.os.replace",
                       side_effect=AssertionError("unneeded replacement")):
                self.assertFalse(state.save(target))
            self.assertEqual(first,target.read_bytes())
            self.assertEqual(stamp,target.stat().st_mtime_ns)
            self.assertEqual(["state.json"],[p.name for p in Path(directory).iterdir()])

    def test_json_key_order_differences_do_not_trigger_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"state.json"
            a=DeliveryState({"z":200,"a":100},{"warm:z":"initialized","warm:a":"initialized"})
            self.assertTrue(a.save(target))
            b=DeliveryState({"a":100,"z":200},{"warm:a":"initialized","warm:z":"initialized"})
            with patch("community.state.os.replace",
                       side_effect=AssertionError("key ordering should be canonical")):
                self.assertFalse(b.save(target))

    def test_changed_acknowledgement_or_cursor_creates_durable_update(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"state.json"
            state=DeliveryState()
            self.assertTrue(state.save(target))
            self.assertFalse(state.save(target))
            state.mark_delivered("alpha","event-1",999)
            self.assertTrue(state.save(target))
            self.assertTrue(DeliveryState.load(target).was_delivered("alpha","event-1"))
            state.cursors["health:x"]="retry"
            self.assertTrue(state.save(target))
            restored=DeliveryState.load(target)
            self.assertEqual("retry",restored.cursors["health:x"])
            self.assertTrue(restored.was_delivered("alpha","event-1"))
            self.assertFalse(state.save(target))

    def test_atomic_failure_keeps_previous_state_and_no_leftover_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"state.json"
            state=DeliveryState()
            state.mark_delivered("alpha","old-event",12)
            self.assertTrue(state.save(target))
            before=target.read_bytes()
            state.mark_delivered("alpha","new-event",13)
            with patch("community.state.os.replace",
                       side_effect=OSError("simulated local disk failure")):
                with self.assertRaises(OSError):
                    state.save(target)
            self.assertEqual(before,target.read_bytes())
            self.assertEqual(["state.json"],[p.name for p in Path(directory).iterdir()])
            self.assertTrue(DeliveryState.load(target).was_delivered("alpha","old-event"))
            self.assertFalse(DeliveryState.load(target).was_delivered("alpha","new-event"))

    def test_runner_reports_state_change_only_on_actual_file_change(self):
        from community_runner import main
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=root/"community.json"
            target=root/"community_deliveries.json"
            config.write_text(json.dumps({
                "version":1,"sources":[],"destinations":[],
                "subscriptions":[],"scheduled_events":[],
            }),encoding="utf8")
            env={
                "COMMUNITY_CONFIG_FILE":str(config),
                "COMMUNITY_STATE_FILE":str(target),
                "COMMUNITY_DRY_RUN":"false",
            }
            with patch.dict("os.environ",env), \
                 patch("community_runner.credential_environment",return_value={}):
                first=io.StringIO()
                with redirect_stdout(first):
                    self.assertEqual(0,main([]))
                self.assertTrue(target.exists())
                self.assertIn("state_changed=yes",first.getvalue())
                before=target.stat().st_mtime_ns
                second=io.StringIO()
                with redirect_stdout(second), \
                     patch("community.state.os.replace",
                           side_effect=AssertionError("never rewrite unchanged state")):
                    self.assertEqual(0,main([]))
                self.assertIn("state_changed=no",second.getvalue())
                self.assertEqual(before,target.stat().st_mtime_ns)

    def test_dry_run_cannot_create_first_state_file(self):
        from community_runner import main
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=root/"config.json"
            target=root/"not-created.json"
            config.write_text(json.dumps({
                "version":1,"sources":[],"destinations":[],"subscriptions":[],
            }),encoding="utf8")
            env={
                "COMMUNITY_CONFIG_FILE":str(config),
                "COMMUNITY_STATE_FILE":str(target),
                "COMMUNITY_DRY_RUN":"true",
            }
            with patch.dict("os.environ",env), \
                 patch("community_runner.credential_environment",return_value={}):
                out=io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(0,main([]))
            self.assertIn("state_changed=no",out.getvalue())
            self.assertFalse(target.exists())


if __name__=="__main__":
    unittest.main()
