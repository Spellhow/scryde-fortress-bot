"""Offline atomic BSOE source-state candidate, never production cutover."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from community.config import parse_config
from community.legacy_cutover import prepare_bsoe_history_checkpoints
from community.legacy_forum_bridge import forum_watermark_key
from community.legacy_telegram_bridge import watermark_key
from community.state import DeliveryState
from scripts.prepare_bsoe_history import main as combined_cli

SENSITIVE="SENSITIVE-OLD-POST-OR-TOKEN"
WORLD={"network":"Scryde","name":"x1000"}
TELEGRAM="https://t.me/s/scryde"
FORUM="https://board.scryde.net/threads/obnovlenija.30694/page-18"


def config():
    return {
        "version":1,
        "sources":[
            {"id":"telegram-source","kind":"telegram_public",
             "url":TELEGRAM,"world":WORLD},
            {"id":"forum-source","kind":"scryde_forum",
             "url":FORUM,"world":WORLD,"include_keywords":["x1000"]},
        ],
        "destinations":[{"id":"channel","kind":"telegram",
                         "address_env":"TG_DESTINATION","token_env":"TG_TOKEN"}],
        "subscriptions":[
            {"destination_id":"channel","world":WORLD,"source_ids":["telegram-source"]},
            {"destination_id":"channel","world":WORLD,"source_ids":["forum-source"]},
        ],
    }


def old():
    return {
        "news":{"last_seen_id":105,"sent_ids":[100,103],
                "pending":[{"post_id":103,"status":"published","text":SENSITIVE},
                           {"post_id":104,"status":"cancelled","text":SENSITIVE}]},
        "forum_news":{"last_seen_id":250,"sent_ids":[247,248],
                     "pending":[{"post_id":247,"status":"published","text":SENSITIVE},
                                {"post_id":249,"status":"expired","text":SENSITIVE}]},
        "meta":{"tg_update_offset":99999,"moderation_secret":SENSITIVE},
    }


class CombinedBSOECheckpointTests(unittest.TestCase):
    def setUp(self):
        self.cfg=parse_config(config())

    def combine(self, old_state=None, current=None):
        return prepare_bsoe_history_checkpoints(
            old_state if old_state is not None else old(),
            self.cfg,
            telegram_source="telegram-source",
            forum_source="forum-source",
            destination="channel",
            current=current if current is not None else DeliveryState(),
        )

    def test_two_scoped_markers_and_original_state_unchanged(self):
        original=old()
        baseline=copy.deepcopy(original)
        current=DeliveryState({"old-receipt":123},{"warm:source":"initialized"})
        combined=self.combine(original,current)
        keys={
            watermark_key(self.cfg.sources[0],"channel"):"105",
            forum_watermark_key(self.cfg.sources[1],"channel"):"250",
        }
        self.assertEqual({"warm:source":"initialized",**keys},combined.cursors)
        self.assertEqual({"old-receipt":123},combined.delivered)
        self.assertEqual(baseline,original)
        self.assertEqual({"warm:source":"initialized"},current.cursors)
        serialized=json.dumps({"delivered":combined.delivered,"cursors":combined.cursors})
        self.assertNotIn(SENSITIVE,serialized)
        self.assertNotIn("tg_update_offset",serialized)
        self.assertNotIn(TELEGRAM,serialized)
        self.assertNotIn(FORUM,serialized)

    def test_one_bad_forum_history_refuses_both_markers(self):
        data=old()
        data["forum_news"]["pending"].append({"post_id":250,"status":"approved"})
        existing=DeliveryState({"old-receipt":1},{"safe":"keep"})
        prior=copy.deepcopy(existing.cursors)
        with self.assertRaises(ValueError):
            self.combine(data,existing)
        self.assertEqual(prior,existing.cursors)

    def test_one_bad_telegram_history_refuses_both_markers(self):
        data=old()
        data["news"]["pending"].append({"post_id":105,"status":"pending"})
        with self.assertRaises(ValueError):
            self.combine(data)

    def test_wrong_source_and_destination_refused(self):
        with self.assertRaises(ValueError):
            prepare_bsoe_history_checkpoints(
                old(),self.cfg,
                telegram_source="forum-source",
                forum_source="telegram-source",
                destination="channel",current=DeliveryState()
            )
        with self.assertRaises(ValueError):
            prepare_bsoe_history_checkpoints(
                old(),self.cfg,
                telegram_source="telegram-source",
                forum_source="telegram-source",
                destination="channel",current=DeliveryState()
            )
        with self.assertRaises(ValueError):
            prepare_bsoe_history_checkpoints(
                old(),self.cfg,
                telegram_source="telegram-source",
                forum_source="forum-source",
                destination="wrong",current=DeliveryState()
            )

    def test_replay_idempotent_same_old_state_and_conflict_refused(self):
        first=self.combine()
        second=self.combine(current=first)
        self.assertEqual(first.cursors,second.cursors)
        other=old()
        other["news"]["last_seen_id"]=106
        with self.assertRaises(ValueError):
            self.combine(other,first)

    def test_cli_reproduces_real_legacy_state_dry_run(self):
        source=Path(__file__).resolve().parent/"site_state.json"
        if not source.exists():
            self.skipTest("No tracked state in checkout")
        original_mtime=source.stat().st_mtime_ns
        with tempfile.TemporaryDirectory() as folder:
            cfg=Path(folder)/"community.json"
            cfg.write_text(json.dumps(config()),encoding="utf8")
            state=Path(folder)/"does-not-exist.json"
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                result=combined_cli([
                    "--legacy",str(source),"--config",str(cfg),
                    "--current",str(state),
                    "--telegram-source","telegram-source",
                    "--forum-source","forum-source",
                    "--destination","channel",
                ])
            self.assertEqual(0,result)
            report=json.loads(out.getvalue())
            self.assertEqual(2,report["public_sources_validated"])
            self.assertEqual(2,report["new_checkpoint_markers"])
            self.assertFalse(report["cutover_authorized"])
            self.assertFalse(report["output_written"])
            self.assertFalse(state.exists())
        self.assertEqual(original_mtime,source.stat().st_mtime_ns)

    def test_cli_explicit_candidate_has_exactly_two_hash_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            cfg=root/"config.json"
            legacy=root/"legacy.json"
            current=root/"current.json"
            output=root/"candidate.json"
            cfg.write_text(json.dumps(config()),encoding="utf8")
            legacy.write_text(json.dumps(old()),encoding="utf8")
            DeliveryState({"prior-receipt":42},{"warm:prior":"initialized"}).save(current)
            args=[
                "--legacy",str(legacy),
                "--config",str(cfg),
                "--current",str(current),
                "--telegram-source","telegram-source",
                "--forum-source","forum-source",
                "--destination","channel",
            ]
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2,combined_cli(args+["--output",str(output)]))
            self.assertFalse(output.exists())
            stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(0,combined_cli(args+[
                    "--output",str(output),"--confirm",
                ]))
            self.assertTrue(json.loads(stdout.getvalue())["output_written"])
            payload=json.loads(output.read_text())
            self.assertEqual(3,len(payload["cursors"]))
            self.assertIn("prior-receipt",payload["delivered"])
            self.assertNotIn(SENSITIVE,output.read_text())
            self.assertEqual(2,len([
                key for key in payload["cursors"]
                if key.startswith("legacy-")
            ]))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2,combined_cli(args+[
                    "--output",str(output),"--confirm",
                ]))
            self.assertEqual(json.loads(legacy.read_text()),old())
            self.assertEqual({"warm:prior":"initialized"},DeliveryState.load(current).cursors)

    def test_cli_failure_redacts_private_content_and_keeps_output_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            cfg=root/"config.json"
            legacy=root/"legacy.json"
            output=root/"candidate.json"
            cfg.write_text(json.dumps(config()),encoding="utf8")
            bad=old()
            bad["forum_news"]["pending"].append({"post_id":250,"status":"pending","text":SENSITIVE})
            legacy.write_text(json.dumps(bad),encoding="utf8")
            stderr=io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(2,combined_cli([
                    "--legacy",str(legacy),"--config",str(cfg),
                    "--current",str(root/"missing.json"),
                    "--telegram-source","telegram-source",
                    "--forum-source","forum-source",
                    "--destination","channel",
                    "--output",str(output),"--confirm",
                ]))
            self.assertFalse(output.exists())
            self.assertNotIn(SENSITIVE,stderr.getvalue())


if __name__=="__main__":
    unittest.main()
