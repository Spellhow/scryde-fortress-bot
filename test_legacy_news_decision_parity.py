"""Offline parity of legacy moderation queue action decisions and side effects."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import github_runner as bot
from community.legacy_news_decisions import (
    classify_news_queue_item, summarize_legacy_news_queue, DECISION_CATEGORIES,
)
from scripts.replay_legacy_news import main as replay_main

NOW = 2_000_000_000
PRIVATE = "DO-NOT-PRINT-PRIVATE-NEWS-BODY-OR-TOKEN"


def news_item(
    status="pending", *, created=NOW-3600, publish_after=NOW-60,
    post_id=42, debug=False,
):
    return {
        "post_id": post_id,
        "status": status,
        "title": PRIVATE,
        "text": PRIVATE,
        "url": "https://example.invalid/source/private",
        "created_at": created,
        "publish_after": publish_after,
        "debug_message_id": 9 if debug else None,
        "source": "telegram",
    }


def state(items, key="news"):
    data={
        "news": {"pending":[], "sent_ids":[], "last_seen_id":0},
        "forum_news": {"pending":[], "sent_ids":[], "last_seen_id":0},
    }
    data[key]["pending"] = copy.deepcopy(items)
    return data


class QueueDecisionParityTests(unittest.TestCase):
    def test_table_of_legacy_boundary_conditions_matches_actual_runtime(self):
        cases = [
            ("ignored published", "published", NOW-30, NOW-30, "prod", "ignore"),
            ("ignored cancelled", "cancelled", NOW-30, NOW-30, "prod", "ignore"),
            ("expired old pending", "pending", NOW-86401, NOW-10, "prod", "expire_age"),
            ("at age boundary", "pending", NOW-86400, NOW-60, "prod", "publish"),
            ("waiting future", "pending", NOW-120, NOW+60, "prod", "wait_schedule"),
            ("waiting future approved", "approved", NOW-120, NOW+60, "prod", "wait_schedule"),
            ("debug paused", "pending", NOW-120, NOW-30, "debug", "wait_debug"),
            ("debug too old", "pending", NOW-86401, NOW-30, "debug", "expire_age"),
            ("at grace boundary", "pending", NOW-3600, NOW-1800, "prod", "publish"),
            ("past grace", "pending", NOW-3600, NOW-1801, "prod", "expire_late"),
            ("no publish timestamp", "pending", NOW-3600, 0, "prod", "publish"),
            ("approved old but explicit", "approved", NOW-172800, NOW-15000, "prod", "publish"),
            ("approved no timestamp", "approved", NOW-172800, 0, "prod", "publish"),
        ]
        for label,status,created,publish_after,mode,expected in cases:
            with self.subTest(case=label):
                item = news_item(status,created=created,publish_after=publish_after)
                before = copy.deepcopy(item)
                decision = classify_news_queue_item(
                    item, now=NOW, expire_hours=24, grace_minutes=30,
                    target_chat=mode
                )
                self.assertEqual(expected,decision)
                self.assertEqual(before,item)
                snapshot = state([item])
                with patch.object(bot.time,"time",return_value=NOW), \
                     patch.object(bot,"NEWS_TARGET_CHAT",mode), \
                     patch.object(bot,"NEWS_PENDING_EXPIRE_HOURS",24), \
                     patch.object(bot,"NEWS_AUTO_PUBLISH_GRACE_MIN",30), \
                     patch.object(bot,"TG_CHAT_DEBUG",""), \
                     patch.object(bot,"send_telegram",return_value=True) as send:
                    bot.process_pending_news_queue(snapshot)
                actual = snapshot["news"]["pending"][0]
                if expected == "publish":
                    self.assertEqual("published",actual["status"])
                    send.assert_called_once()
                elif expected.startswith("expire"):
                    self.assertEqual("expired",actual["status"])
                    send.assert_not_called()
                else:
                    self.assertEqual(status,actual["status"])
                    send.assert_not_called()

    def test_failed_publish_does_not_claim_success(self):
        for status in ("pending","approved"):
            with self.subTest(status=status):
                snapshot=state([news_item(status)])
                with patch.object(bot.time,"time",return_value=NOW), \
                     patch.object(bot,"NEWS_TARGET_CHAT","prod"), \
                     patch.object(bot,"TG_CHAT_DEBUG",""), \
                     patch.object(bot,"send_telegram",return_value=False) as send:
                    bot.process_pending_news_queue(snapshot)
                send.assert_called_once()
                self.assertEqual(status,snapshot["news"]["pending"][0]["status"])

    def test_different_news_sections_have_distinct_counts_without_leaking_content(self):
        snapshot=state([news_item("pending",created=NOW-90000)], "news")
        snapshot["forum_news"]["pending"]=[
            news_item("approved",created=NOW-90000),
            news_item("published"),
        ]
        original=copy.deepcopy(snapshot)
        report=summarize_legacy_news_queue(
            snapshot,now=NOW,expire_hours=24,grace_minutes=30,target_chat="prod"
        )
        self.assertEqual(1,report["sections"]["news"]["expire_age"])
        self.assertEqual(1,report["sections"]["forum_news"]["publish"])
        self.assertEqual(1,report["sections"]["forum_news"]["ignore"])
        self.assertFalse(report["cutover_authorized"])
        self.assertNotIn(PRIVATE,json.dumps(report))
        self.assertEqual(original,snapshot)

    def test_preview_never_counts_publish_as_delivery(self):
        report=summarize_legacy_news_queue(
            state([news_item()]),now=NOW,expire_hours=24,
            grace_minutes=30,target_chat="prod"
        )
        self.assertEqual(1,report["sections"]["news"]["publish"])
        self.assertNotIn("sent",report["sections"]["news"])
        self.assertFalse(report["cutover_authorized"])

    def test_malformed_entries_are_anonymized_not_logged(self):
        snapshot=state([
            news_item("pending"),
            {"status":"pending","created_at":"not-a-timestamp","text":PRIVATE},
            {"status":["malformed"],"text":PRIVATE},
            PRIVATE,
        ])
        report=summarize_legacy_news_queue(
            snapshot,now=NOW,expire_hours=24,grace_minutes=30,target_chat="prod"
        )
        self.assertEqual(2,report["sections"]["news"]["invalid"])
        self.assertEqual(1,report["sections"]["news"]["ignore"])
        self.assertNotIn(PRIVATE,json.dumps(report))
        self.assertEqual(4,report["sections"]["news"]["items"])

    def test_cli_is_read_only_and_exposes_no_messages_or_paths(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"private-bsoe.json"
            payload=json.dumps(state([news_item(debug=True)]),ensure_ascii=False)
            p.write_text(payload,encoding="utf8")
            out=io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(0,replay_main([
                    "--state",str(p),"--now",str(NOW),"--mode","prod"
                ]))
            self.assertEqual(payload,p.read_text(encoding="utf8"))
            self.assertNotIn(PRIVATE,out.getvalue())
            self.assertNotIn(str(p),out.getvalue())
            self.assertFalse(json.loads(out.getvalue())["cutover_authorized"])

    def test_cli_rejects_malformed_state_without_exposing_contents(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"private.json"
            p.write_text("{" + PRIVATE,encoding="utf8")
            output=io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(2,replay_main(["--state",str(p)]))
            self.assertNotIn(PRIVATE,output.getvalue())
            self.assertNotIn(str(p),output.getvalue())

    def test_debug_mode_never_attempts_auto_publish(self):
        report=summarize_legacy_news_queue(
            state([news_item("pending"),news_item("approved")]),
            now=NOW,expire_hours=24,grace_minutes=30,target_chat="debug"
        )
        self.assertEqual(2,report["sections"]["news"]["wait_debug"])
        self.assertEqual(0,report["sections"]["news"]["publish"])

    def test_report_categories_are_fixed(self):
        report=summarize_legacy_news_queue(
            state([news_item()]),now=NOW,expire_hours=24,
            grace_minutes=30,target_chat="prod"
        )
        self.assertEqual(
            {"items","invalid",*DECISION_CATEGORIES},
            set(report["sections"]["news"]),
        )

    def test_tracked_state_read_only_smoke(self):
        tracked=Path(__file__).resolve().parent/"site_state.json"
        if not tracked.exists():
            self.skipTest("No tracked state in checkout")
        before=tracked.stat().st_mtime_ns
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            rc=replay_main(["--state",str(tracked),"--now",str(NOW),"--mode","prod"])
        self.assertEqual(0,rc)
        report=json.loads(out.getvalue())
        self.assertIn("news",report["sections"])
        self.assertIn("forum_news",report["sections"])
        self.assertFalse(report["cutover_authorized"])
        self.assertEqual(before,tracked.stat().st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
