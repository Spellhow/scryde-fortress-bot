import unittest
from unittest import mock

import github_runner as bot


class FortressLossSignalTests(unittest.TestCase):
    def make_state(self):
        obj = bot.default_object_state()
        obj.update(
            {
                "had": True,
                "name": "Antharas Fortress",
                "id": 116,
                "owner_image": "bsoe.jpg",
            }
        )
        section = dict(obj)
        section["objects"] = {"116": dict(obj)}
        section["_root_state"] = {"meta": {"last_alerts": {}}}
        return section

    @mock.patch.object(bot, "build_event_card", return_value=None)
    @mock.patch.object(bot, "send_notification", return_value=True)
    def test_missing_row_does_not_mark_fortress_lost(self, send_notification, _card):
        state = self.make_state()
        result = bot.process_defence(state, [], "fortress", bot.FORTRESS_URL)
        self.assertTrue(result["objects"]["116"]["had"])
        self.assertFalse(result["objects"]["116"]["notified_lost"])
        send_notification.assert_not_called()

    @mock.patch.object(bot, "build_event_card", return_value=None)
    @mock.patch.object(bot, "send_notification", return_value=True)
    def test_explicit_npc_owner_marks_fortress_lost_immediately(self, send_notification, _card):
        state = self.make_state()
        items = [
            {
                "id": 116,
                "name": "Antharas Fortress",
                "owner": None,
                "siege_at": 0,
                "siege_sides": [],
            }
        ]
        result = bot.process_defence(state, items, "fortress", bot.FORTRESS_URL)
        self.assertFalse(result["objects"]["116"]["had"])
        self.assertTrue(result["objects"]["116"]["notified_lost"])
        send_notification.assert_called_once()


if __name__ == "__main__":
    unittest.main()
