"""Legacy runner fail-closed behavior with partial Scryde responses.

Tests are offline, no browser usage, no Telegram, no Gemini. Keep the current
notification behavior for valid rows and defer false cancellation/loss on
ambiguous rankings.
"""
import time
import unittest
from unittest.mock import patch

import github_runner as bot


def row(identifier=116, owner="BSOE", attackers=(), sides=None):
    return {
        "id": identifier,
        "name": "Antharas Fortress",
        "owner": None if owner is None else {"name": owner},
        "siege_at": int(time.time()) + 3600,
        "siege_sides": sides if sides is not None else {"attackers": [{"name": n} for n in attackers]},
    }


def prev_defence():
    old=bot.default_object_state()
    old.update({
        "had": True, "id": 116, "name": "Antharas Fortress",
        "notified_siege": True, "last_siege_at": int(time.time()) + 3600,
        "last_attackers": [{"name":"Enemy"}],
    })
    section=dict(old)
    section["objects"]={"116":dict(old)}
    section["_root_state"]={"meta":{"last_alerts":{}}}
    return section


def prev_attack():
    return {"116": {
        "name":"Antharas Fortress", "siege_at":int(time.time()) + 3600,
        "notified":True,"notified_reminder":False,"notified_at":int(time.time()),
    }}


class ScrydeFailClosedTests(unittest.TestCase):
    def test_safe_get_attackers_malformed_rows(self):
        for item in (None, "bad", {"siege_sides": "corrupt"},
                     {"siege_sides":{"attackers":"not a list"}},
                     {"siege_sides":{"attackers":[None, {"name": 5}]}}):
            with self.subTest(item=item):
                self.assertEqual([],bot.get_attackers(item))

    def test_get_attackers_valid(self):
        self.assertEqual(["BSOE", "Enemy"], bot.get_attackers(row(
            owner="Other", attackers=("BSOE","Enemy"),
        )))

    def test_bad_siege_sides_fails_validation(self):
        self.assertFalse(bot.is_valid_scryde_ranking_row(row(sides={"attackers": "garbage"})))
        self.assertFalse(bot.is_valid_scryde_ranking_row(row(sides="garbage")))
        self.assertTrue(bot.is_valid_scryde_ranking_row(row()))

    def test_missing_owner_does_not_prove_npc_capture(self):
        item=row()
        item.pop("owner")
        self.assertFalse(bot.is_valid_scryde_ranking_row(item))
        self.assertTrue(bot.is_valid_scryde_ranking_row(row(owner=None)))

    def test_duplicate_ids_are_both_quarantined(self):
        rows, count=bot.valid_scryde_ranking_rows([row(owner="BSOE"),row(owner="Enemy")])
        self.assertEqual([],rows)
        self.assertEqual(1,count)

    @patch.object(bot, "send_notification", return_value=True)
    def test_corrupted_owner_does_not_emit_loss(self, send):
        item=row(owner="Enemy")
        item["owner"]="bad-format"
        state=prev_defence()
        result=bot.process_defence(state,[item],"fortress",bot.FORTRESS_URL)
        self.assertTrue(result["objects"]["116"]["had"])
        send.assert_not_called()

    @patch.object(bot, "send_notification", return_value=True)
    def test_partial_siege_sides_does_not_emit_cancel(self, send):
        item=row(owner="BSOE")
        item["siege_sides"]={"attackers":None}
        state=prev_defence()
        result=bot.process_defence(state,[item],"fortress",bot.FORTRESS_URL)
        self.assertTrue(result["objects"]["116"]["notified_siege"])
        send.assert_not_called()

    @patch.object(bot, "send_telegram", return_value=True)
    @patch.object(bot, "send_notification", return_value=True)
    def test_partial_attack_source_does_not_cancel_existing_attack(self, notify, telegram):
        previous=prev_attack()
        broken=row(owner="Other", attackers=("BSOE",))
        broken["siege_sides"]={"attackers":"not a list"}
        result=bot.process_our_attacks(previous,[broken],"fortress",bot.FORTRESS_URL)
        self.assertIn("116",result)
        telegram.assert_not_called()
        notify.assert_not_called()

    @patch.object(bot, "send_telegram", return_value=True)
    @patch.object(bot, "send_notification", return_value=True)
    def test_missing_attack_row_defers_without_unverified_cancellation(self, notify, telegram):
        previous=prev_attack()
        result=bot.process_our_attacks(previous, [row(identifier=117, owner="BSOE")],
                                       "fortress",bot.FORTRESS_URL)
        self.assertIn("116",result)
        telegram.assert_not_called()
        notify.assert_not_called()

    @patch.object(bot, "build_event_card", return_value=None)
    @patch.object(bot, "send_notification", return_value=True)
    def test_explicit_new_owner_still_reports_loss(self, notify, card):
        state=prev_defence()
        result=bot.process_defence(state,[row(owner="Enemy")],
                                   "fortress",bot.FORTRESS_URL)
        self.assertTrue(result["objects"]["116"]["notified_lost"])
        self.assertFalse(result["objects"]["116"]["had"])
        notify.assert_called_once()


if __name__ == "__main__":
    unittest.main()
