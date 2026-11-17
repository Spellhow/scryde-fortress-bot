"""Only an explicitly observed trusted ranking row can prove withdrawal.

Missing rows, malformed sources and changed ownership do not generate a
misleading BSOE 'we cancelled our siege' notification.
"""
import copy
import unittest
from unittest.mock import patch

import github_runner as bot
from community.adapters.scryde_decisions import project_scryde_decisions
from community.adapters.scryde_siege_rules import missing_own_attack_action

NOW=1800000000
URL="https://ua.scryde.game/rankings/1000/fortresses"


def ranking(object_id, owner="Enemy", attackers=(), siege_at=NOW+3600):
    return {
        "id":object_id,"name":"Gludio Castle",
        "owner":{"name":owner} if owner is not None else None,
        "siege_sides":{"attackers":[{"name":name} for name in attackers]},
        "siege_at":siege_at,
    }


def previous(object_id):
    return {
        str(object_id):{
            "name":"Gludio Castle",
            "siege_at":NOW+3600,
            "notified":True,
            "notified_at":NOW-3600,
            "notified_reminder":False,
        }
    }


class CancellationEvidenceTests(unittest.TestCase):
    def runner(self, initial, rows, kind, *, now=NOW, accepted=True):
        state=copy.deepcopy(initial)
        messages=[]
        def capture(text):
            messages.append(text)
            return accepted
        with patch.object(bot,"send_telegram",side_effect=capture), \
             patch.object(bot,"send_notification",return_value=True) as alert, \
             patch.object(bot.time,"time",return_value=now):
            result=bot.process_our_attacks(state,rows,kind,URL)
        alert.assert_not_called()
        return result,messages

    def test_missing_object_is_not_verified_cancellation_for_both_types(self):
        for kind in ("castle","fortress"):
            for rows in ([],[ranking(42)], [ranking(42),ranking(44)]):
                with self.subTest(kind=kind,rows=len(rows)):
                    initial=previous(116)
                    final,messages=self.runner(initial,rows,kind)
                    self.assertEqual(initial,final)
                    self.assertEqual([],messages)

    def test_owned_now_means_resolved_not_explicitly_cancelled(self):
        for kind in ("castle","fortress"):
            for attackers in ((),("BSOE",)):
                with self.subTest(kind=kind,attackers=attackers):
                    final,messages=self.runner(previous(116),[
                        ranking(116,owner="BSOE",attackers=attackers)
                    ],kind)
                    self.assertEqual({},final)
                    self.assertEqual([],messages)

    def test_observed_other_owner_without_our_attack_is_real_cancellation(self):
        for kind in ("castle","fortress"):
            for owner in ("Enemy",None):
                with self.subTest(kind=kind,owner=owner):
                    final,messages=self.runner(
                        previous(116),[ranking(116,owner=owner,attackers=())],kind
                    )
                    self.assertEqual({},final)
                    self.assertEqual(1,len(messages))
                    self.assertIn("знявся",messages[0])

    def test_unconfirmed_explicit_cancellation_keeps_state_for_retry(self):
        current=previous(116)
        rows=[ranking(116,owner="Enemy",attackers=())]
        failed,messages=self.runner(current,rows,"fortress",accepted=False)
        self.assertEqual(current,failed)
        self.assertEqual(1,len(messages))
        done,messages=self.runner(failed,rows,"fortress",accepted=True)
        self.assertEqual({},done)
        self.assertEqual(1,len(messages))

    def test_malformed_or_duplicate_observations_never_fake_cancellation(self):
        broken=ranking(116)
        broken.pop("owner")
        conflicting=[ranking(116,owner="Enemy"), ranking(116,owner="BSOE")]
        for rows in ([broken],conflicting):
            with self.subTest(rows=rows):
                initial=previous(116)
                final,messages=self.runner(initial,rows,"fortress")
                self.assertEqual(initial,final)
                self.assertEqual([],messages)

    def test_expired_registration_cleans_up_without_notification_even_if_missing(self):
        final,messages=self.runner(previous(116),[],"fortress",now=NOW+3600)
        self.assertEqual({},final)
        self.assertEqual([],messages)

    def test_projection_and_runtime_agree_on_ambiguous_and_verified_cases(self):
        prior=previous(116)
        defence={"objects":{}}
        for rows,expected in (
            ([],False),
            ([ranking(42)],False),
            ([ranking(116,owner="BSOE")],False),
            ([ranking(116,owner="Enemy",attackers=())],True),
        ):
            with self.subTest(rows=rows):
                projection=project_scryde_decisions(
                    rows,clan="BSOE",object_type="fortress",
                    defence_state=defence,attack_state=prior,now=NOW
                )
                predicted=any(
                    item.kind=="our_attack_cancelled" for item in projection.decisions
                )
                self.assertEqual(expected,predicted)
                _,messages=self.runner(prior,rows,"fortress")
                self.assertEqual(expected,bool(messages))


if __name__=="__main__":
    unittest.main()
