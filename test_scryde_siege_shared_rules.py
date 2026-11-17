"""Exact shared siege decision boundaries and offline live-runner comparisons."""
import copy
import unittest
from unittest.mock import patch

import github_runner as bot
from community.adapters.scryde_siege_rules import (
    defence_attack_changed, defence_reminder_due,
    defence_cancellation_action, own_attack_action,
    missing_own_attack_action,
)
from test_scryde_decision_parity import LegacyDecisionParity, defence, row, NOW

URL = "https://ua.scryde.game/rankings/1000/fortresses"


class PureSiegeRuleTests(unittest.TestCase):
    def test_defence_attacker_reorder_is_not_new_attack(self):
        old={"notified_siege":True,"last_attackers":[{"name":"B"},{"name":"A"}],
             "last_siege_at":NOW+3600}
        before=copy.deepcopy(old)
        self.assertFalse(defence_attack_changed(old,["A","B"],NOW+3600))
        self.assertTrue(defence_attack_changed(old,["A","C"],NOW+3600))
        self.assertTrue(defence_attack_changed(old,["A","B"],NOW+5000))
        self.assertEqual(before,old)

    def test_new_defence_requires_initial_notification(self):
        self.assertTrue(defence_attack_changed({},["Enemy"],NOW+1200))
        self.assertTrue(defence_attack_changed({"notified_siege":False},["Enemy"],NOW+1200))

    def test_defence_reminder_exact_25_minutes_and_minimum_notice_gap(self):
        state={"notified_siege":True,"notified_reminder":False,
               "siege_first_notify":NOW-5400}
        self.assertTrue(defence_reminder_due(state,NOW+25*60,NOW))
        self.assertFalse(defence_reminder_due(state,NOW+26*60,NOW))
        self.assertFalse(defence_reminder_due(state,NOW+30,NOW))
        self.assertFalse(defence_reminder_due(state,NOW+0,NOW))
        self.assertFalse(defence_reminder_due(
            dict(state,siege_first_notify=NOW-5399),NOW+1200,NOW))
        self.assertFalse(defence_reminder_due(
            dict(state,notified_reminder=True),NOW+1200,NOW))

    def test_defence_cancellation_is_expiry_after_start(self):
        state={"notified_siege":True,"last_siege_at":NOW+600}
        self.assertEqual("notify",defence_cancellation_action(state,NOW))
        self.assertEqual("expire",defence_cancellation_action(
            dict(state,last_siege_at=NOW),NOW))
        self.assertEqual("notify",defence_cancellation_action(
            dict(state,last_siege_at=0),NOW))
        self.assertEqual("none",defence_cancellation_action({},NOW))

    def test_own_new_attack_and_changed_date(self):
        self.assertEqual("register",own_attack_action({},NOW+3600,NOW))
        previous={"notified":True,"siege_at":NOW+3600,"notified_at":NOW-100}
        self.assertEqual("register",own_attack_action(previous,NOW+7200,NOW))
        self.assertEqual("none",own_attack_action(previous,NOW+3600,NOW))

    def test_own_reminder_exact_gap_and_expiry_boundaries(self):
        previous={"notified":True,"notified_reminder":False,"siege_at":NOW+1800,
                  "notified_at":NOW-1800}
        self.assertEqual("remind",own_attack_action(previous,NOW+1800,NOW))
        self.assertEqual("none",own_attack_action(
            dict(previous,notified_at=NOW-1799),NOW+1800,NOW))
        self.assertEqual("none",own_attack_action(
            dict(previous,siege_at=NOW+1801),NOW+1801,NOW))
        self.assertEqual("none",own_attack_action(
            dict(previous,siege_at=NOW),NOW,NOW))
        self.assertEqual("none",own_attack_action(
            dict(previous,notified_reminder=True),NOW+1800,NOW))

    def test_disappeared_registration_requires_observed_evidence(self):
        other_owner={"owner":{"name":"Enemy"}}
        own_owner={"owner":{"name":"BSOE"}}
        self.assertEqual("defer",missing_own_attack_action({"siege_at":0},NOW))
        self.assertEqual("defer",missing_own_attack_action(
            {"siege_at":NOW+1},NOW))
        self.assertEqual("cancel",missing_own_attack_action(
            {"siege_at":NOW+1},NOW,observed_row=other_owner,clan="BSOE"))
        self.assertEqual("owner_changed",missing_own_attack_action(
            {"siege_at":NOW+1},NOW,observed_row=own_owner,clan="BSOE"))
        self.assertEqual("expire",missing_own_attack_action(
            {"siege_at":NOW},NOW))
        self.assertEqual("expire",missing_own_attack_action(
            {"siege_at":NOW-1},NOW))


class ActualLegacySharedRuleTests(unittest.TestCase):
    def test_defence_projection_and_mocked_runtime_match_reminder_edges(self):
        cases=[
            (NOW-5400,NOW+1500,True),
            (NOW-5399,NOW+1500,False),
            (NOW-5400,NOW+1560,False),
            (NOW-5400,NOW+60,True),
        ]
        parity=LegacyDecisionParity()
        for first,siege_at,expected in cases:
            with self.subTest(first=first,siege_at=siege_at):
                section=defence(had=True,notified_siege=True,attackers=("Enemy",),
                                first=first,siege_at=siege_at)
                report=parity.compare(
                    [row(attackers=("Enemy",),siege_at=siege_at)],
                    section=section,
                )
                self.assertEqual(
                    expected,any(x.kind=="defence_reminder" for x in report.decisions)
                )

    def test_own_attack_failed_notice_then_retry_no_false_success(self):
        actual={}
        observed=[row(owner="Enemy",attackers=("BSOE",),siege_at=NOW+3600)]
        calls=[]
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"build_event_card",return_value=None), \
             patch.object(bot,"send_notification",
                          side_effect=lambda msg,image:calls.append(msg) or False):
            bot.process_our_attacks(actual,observed,"fortress",URL)
        self.assertEqual({},actual)
        self.assertEqual(1,len(calls))
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"build_event_card",return_value=None), \
             patch.object(bot,"send_notification",return_value=True):
            bot.process_our_attacks(actual,observed,"fortress",URL)
        self.assertTrue(actual["116"]["notified"])

    def test_own_attack_cancel_failed_then_retry(self):
        state={"116":{"name":"Antharas Fortress","siege_at":NOW+3600,
                      "notified":True,"notified_at":NOW-3600}}
        before=copy.deepcopy(state)
        notifications=[]
        confirmed_absence=[row(owner="Enemy",attackers=(),siege_at=NOW+3600)]
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"send_telegram",
                          side_effect=lambda msg:notifications.append(msg) or False):
            bot.process_our_attacks(state,confirmed_absence,"fortress",URL)
        self.assertEqual(before,state)
        self.assertEqual(1,len(notifications))
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"send_telegram",return_value=True):
            bot.process_our_attacks(state,confirmed_absence,"fortress",URL)
        self.assertEqual({},state)


if __name__=="__main__":
    unittest.main()
