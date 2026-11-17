"""Negative BSOE siege notifications require confirmed delivery before state updates.

Pure offline tests. No site access, Gemini, or real Telegram sends.
"""
import copy
import unittest
from unittest.mock import patch

import github_runner as bot

NOW = 1800000000


def row(object_id, object_type, owner="BSOE", attackers=(), siege_at=NOW + 3600):
    return {
        "id": object_id,
        "name": "Gludio Castle" if object_type == "castle" else "Antharas Fortress",
        "owner": None if owner is None else {"name": owner},
        "siege_at": siege_at,
        "siege_sides": {"attackers": [{"name": name} for name in attackers]},
    }


def prior(object_id, object_type, siege=True, siege_at=NOW+3600):
    old=bot.default_object_state()
    old.update({
        "id":object_id,
        "name":"Gludio Castle" if object_type == "castle" else "Antharas Fortress",
        "had": True,
        "notified_lost":False,
        "notified_siege":siege,
        "last_siege_at":siege_at if siege else 0,
        "last_attackers":[{"name":"Enemy"}] if siege else [],
        "siege_first_notify":NOW-4000 if siege else 0,
        "notified_reminder":bool(siege),
    })
    return dict(old,objects={str(object_id):dict(old)},_root_state={"meta":{"last_alerts":{}}})


class NegativeSiegeAcknowledgementTests(unittest.TestCase):
    def run_defence(self, section, items, obj_type, outcomes):
        sends=[]
        def send(text,image=None):
            sends.append(text)
            return outcomes[len(sends)-1]
        with patch.object(bot,"send_notification",side_effect=send), \
             patch.object(bot,"build_event_card",return_value=None), \
             patch.object(bot.time,"time",return_value=NOW):
            result=bot.process_defence(section,items,obj_type,
                                       "https://example.invalid/ranking")
        return result,sends

    def test_cancellation_failure_keeps_siege_and_retry_succeeds(self):
        for object_type, object_id in (("fortress",116),("castle",42)):
            with self.subTest(object_type=object_type):
                section=prior(object_id,object_type)
                incoming=[row(object_id,object_type,attackers=())]
                after_failure,failed=self.run_defence(section,incoming,object_type,[False])
                status=after_failure["objects"][str(object_id)]
                self.assertTrue(status["notified_siege"])
                self.assertEqual(NOW+3600,status["last_siege_at"])
                self.assertTrue(status["notified_reminder"])
                self.assertEqual(1,len(failed))

                after_success,sent=self.run_defence(after_failure,incoming,object_type,[True])
                status=after_success["objects"][str(object_id)]
                self.assertFalse(status["notified_siege"])
                self.assertEqual(0,status["last_siege_at"])
                self.assertFalse(status["notified_reminder"])
                self.assertEqual(1,len(sent))
                _,again=self.run_defence(after_success,incoming,object_type,[])
                self.assertEqual([],again)

    def test_unconfirmed_loss_preserves_ownership_and_retries(self):
        for object_type, object_id in (("fortress",116),("castle",42)):
            for owner in ("Enemy",None):
                with self.subTest(object_type=object_type,owner=owner):
                    section=prior(object_id,object_type,siege=False)
                    observed=[row(object_id,object_type,owner=owner,attackers=())]
                    after_failure,first=self.run_defence(section,observed,object_type,[False])
                    self.assertEqual(1,len(first))
                    self.assertTrue(after_failure["objects"][str(object_id)]["had"])
                    self.assertTrue(after_failure["had"])
                    self.assertFalse(after_failure["objects"][str(object_id)]["notified_lost"])

                    after_success,second=self.run_defence(after_failure,observed,object_type,[True])
                    self.assertEqual(1,len(second))
                    self.assertFalse(after_success["objects"][str(object_id)]["had"])
                    self.assertTrue(after_success["objects"][str(object_id)]["notified_lost"])
                    self.assertFalse(after_success["had"])
                    _,third=self.run_defence(after_success,observed,object_type,[])
                    self.assertEqual([],third)

    def test_cancellation_after_siege_end_clears_without_stale_notification(self):
        section=prior(116,"fortress",siege_at=NOW-30)
        incoming=[row(116,"fortress",attackers=(),siege_at=0)]
        result,sent=self.run_defence(section,incoming,"fortress",[])
        self.assertFalse(result["objects"]["116"]["notified_siege"])
        self.assertEqual([],sent)

    def test_failed_loss_followed_by_recovery_does_not_send_stale_loss(self):
        section=prior(116,"fortress",siege=False)
        loss=[row(116,"fortress",owner="Enemy")]
        result,_=self.run_defence(section,loss,"fortress",[False])
        result,recovery=self.run_defence(
            result,[row(116,"fortress",owner="BSOE",attackers=())],
            "fortress",[]
        )
        self.assertTrue(result["objects"]["116"]["had"])
        self.assertFalse(result["objects"]["116"]["notified_lost"])
        self.assertEqual([],recovery)

    def test_malformed_data_does_not_trigger_negative_notifications(self):
        section=prior(116,"fortress",siege=True)
        damaged=row(116,"fortress",owner="Enemy")
        damaged.pop("owner")
        result,sent=self.run_defence(section,[damaged],"fortress",[])
        self.assertEqual([],sent)
        self.assertTrue(result["objects"]["116"]["had"])
        self.assertTrue(result["objects"]["116"]["notified_siege"])


if __name__=="__main__":
    unittest.main()
