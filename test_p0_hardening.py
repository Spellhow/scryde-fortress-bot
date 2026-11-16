"""Offline fixtures for multi-object ownership and malformed ranking rows."""

import unittest
from unittest.mock import patch

import github_runner as bot


def own_row(object_id, name):
    return {
        "id": object_id,
        "name": name,
        "owner": {"name": bot.OUR_CLAN, "image": None},
        "siege_at": 0,
        "siege_sides": {"attackers": []},
    }


class SiegeDefenceBaselineTests(unittest.TestCase):
    @patch.object(bot, "send_notification", return_value=True)
    def test_two_owned_fortresses_are_tracked(self, notify):
        section = {"objects": {}, "_root_state": {"meta": {"last_alerts": {}}}}
        rows = [own_row(116, "Antharas Fortress"), own_row(117, "Second Fortress")]
        result = bot.process_defence(section, rows, "fortress", bot.FORTRESS_URL)
        self.assertEqual({"116", "117"}, set(result["objects"]))
        self.assertTrue(result["objects"]["116"]["had"])
        self.assertTrue(result["objects"]["117"]["had"])
        notify.assert_not_called()

    @patch.object(bot, "send_notification", return_value=True)
    def test_malformed_rows_do_not_crash_or_create_false_loss(self, notify):
        section = {"objects": {}, "_root_state": {"meta": {"last_alerts": {}}}}
        rows = [None, "unusable", 3, {}, own_row(116, "Antharas Fortress")]
        result = bot.process_defence(section, rows, "fortress", bot.FORTRESS_URL)
        self.assertEqual({"116"}, set(result["objects"]))
        notify.assert_not_called()

    @patch.object(bot, "send_notification", return_value=True)
    def test_malformed_attack_rows_are_ignored(self, notify):
        result = bot.process_our_attacks(
            {}, [None, "invalid", {}, own_row(116, "Antharas Fortress")],
            "fortress", bot.FORTRESS_URL,
        )
        self.assertEqual({}, result)
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
