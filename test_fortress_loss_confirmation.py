import unittest
from unittest import mock

import github_runner as bot


class FortressLossConfirmationTests(unittest.TestCase):
    def make_state(self, guard_until=0):
        obj = bot.default_object_state()
        obj.update(
            {
                "had": True,
                "name": "Antharas Fortress",
                "id": 116,
                "owner_image": "bsoe.jpg",
                "last_attackers": [{"name": "ValorS", "image": "valor.jpg"}],
                "last_siege_at": 1790659825,
                "notified_siege": True,
                "siege_first_notify": 1790656895,
                "loss_guard_until": guard_until,
            }
        )
        state = dict(obj)
        state["objects"] = {"116": dict(obj)}
        state["_root_state"] = {"meta": {"last_alerts": {}}}
        return state

    def npc_item(self):
        return {"id": 116, "name": "Antharas Fortress", "owner": None, "siege_sides": {"attackers": []}}

    def enemy_item(self):
        return {"id": 116, "name": "Antharas Fortress", "owner": {"name": "ValorS", "image": "valor.jpg"}, "siege_sides": {"attackers": []}}

    @mock.patch.object(bot, "build_event_card", return_value=None)
    @mock.patch.object(bot, "send_notification", return_value=True)
    def test_npc_during_siege_window_is_not_loss(self, send_notification, _card):
        state = self.make_state(guard_until=2000)
        with mock.patch.object(bot.time, "time", return_value=1500):
            result = bot.process_defence(state, [self.npc_item()], "fortress", bot.FORTRESS_URL)
        self.assertTrue(result["objects"]["116"]["had"])
        self.assertFalse(result["objects"]["116"]["notified_lost"])
        self.assertEqual(result["objects"]["116"]["loss_candidate_count"], 1)
        send_notification.assert_not_called()

    @mock.patch.object(bot, "build_event_card", return_value=None)
    @mock.patch.object(bot, "send_notification", return_value=True)
    def test_loss_requires_two_matching_polls(self, send_notification, _card):
        state = self.make_state(guard_until=0)
        with mock.patch.object(bot.time, "time", return_value=3000):
            bot.process_defence(state, [self.enemy_item()], "fortress", bot.FORTRESS_URL)
        send_notification.assert_not_called()
        self.assertTrue(state["objects"]["116"]["had"])

        with mock.patch.object(bot.time, "time", return_value=3600):
            bot.process_defence(state, [self.enemy_item()], "fortress", bot.FORTRESS_URL)
        send_notification.assert_called_once()
        self.assertFalse(state["objects"]["116"]["had"])
        self.assertTrue(state["objects"]["116"]["notified_lost"])

    @mock.patch.object(bot, "build_event_card", return_value=None)
    @mock.patch.object(bot, "send_notification", return_value=True)
    def test_owner_recovery_clears_loss_candidate(self, send_notification, _card):
        state = self.make_state(guard_until=0)
        with mock.patch.object(bot.time, "time", return_value=3000):
            bot.process_defence(state, [self.npc_item()], "fortress", bot.FORTRESS_URL)
        self.assertEqual(state["objects"]["116"]["loss_candidate_count"], 1)

        owned = {
            "id": 116,
            "name": "Antharas Fortress",
            "owner": {"name": bot.OUR_CLAN, "image": "bsoe.jpg"},
            "siege_sides": {"attackers": []},
        }
        with mock.patch.object(bot.time, "time", return_value=3300):
            bot.process_defence(state, [owned], "fortress", bot.FORTRESS_URL)
        self.assertEqual(state["objects"]["116"]["loss_candidate_count"], 0)
        self.assertIsNone(state["objects"]["116"]["loss_candidate_owner"])
        self.assertFalse(state["objects"]["116"]["notified_lost"])
        self.assertTrue(state["objects"]["116"]["had"])


if __name__ == "__main__":
    unittest.main()
