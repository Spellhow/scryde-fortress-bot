"""Explicit unowned/NPC Scryde registrations must survive adapter migration.

No browser, Telegram, Gemini or real ranking requests.
"""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from community.adapters.scryde import ScrydeRankingAdapter
from community.adapters.scryde_rows import is_valid_scryde_ranking_row
from community.models import World, Provenance, Subscription
import github_runner as bot

NOW=1800000000
FUTURE=2000000000
WORLD=World("Scryde","x1000")


def row(owner=None, attackers=("BSOE",), siege_at=FUTURE):
    return {
        "id":116,
        "name":"Antharas Fortress",
        "owner":None if owner is None else {"name":owner},
        "siege_at":siege_at,
        "siege_sides":{"attackers":[{"name":name} for name in attackers]},
    }


class NpcAttackParityTests(unittest.TestCase):
    def setUp(self):
        self.adapter=ScrydeRankingAdapter("official-scryde","https://example.invalid/ranking")

    def test_explicit_npc_owner_generates_observed_registration(self):
        sample=row()
        self.assertTrue(is_valid_scryde_ranking_row(sample))
        events=self.adapter.parse([sample],world=WORLD)
        self.assertEqual(1,len(events))
        event=events[0]
        self.assertEqual("siege_registration",event.kind)
        self.assertEqual("fortress:116:2000000000",event.external_id)
        self.assertEqual(Provenance.OBSERVED,event.provenance)
        self.assertIsNone(event.clan)
        self.assertIn("Owner: NPC (unowned)",event.body)
        self.assertIn("BSOE",event.body)
        self.assertEqual(datetime.fromtimestamp(FUTURE,tz=timezone.utc),event.occurs_at)

    def test_old_bsoe_sees_same_explicit_npc_attack_registration(self):
        source=row()
        notices=[]
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"build_event_card",return_value=None), \
             patch.object(bot,"send_notification",
                          side_effect=lambda msg,image:notices.append(msg) or True):
            attack_state=bot.process_our_attacks(
                {},[source],"fortress","https://example.invalid/ranking"
            )
        self.assertEqual(1,len(notices))
        self.assertIn("NPC",notices[0])
        self.assertTrue(attack_state["116"]["notified"])
        self.assertEqual(1,len(self.adapter.parse([source],world=WORLD)))

    def test_missing_owner_field_is_not_a_valid_npc_row(self):
        source=row()
        source.pop("owner")
        self.assertFalse(is_valid_scryde_ranking_row(source))
        self.assertEqual([],self.adapter.parse([source],world=WORLD))

    def test_invalid_owner_is_not_misread_as_unowned(self):
        for owner in ("",[],{},123):
            with self.subTest(owner=owner):
                source=row()
                source["owner"]=owner
                self.assertFalse(is_valid_scryde_ranking_row(source))
                self.assertEqual([],self.adapter.parse([source],world=WORLD))

    def test_duplicate_npc_and_other_owner_quarantined(self):
        items=[row(owner=None),row(owner="Enemy")]
        self.assertEqual([],self.adapter.parse(items,world=WORLD))

    def test_unowned_object_without_attackers_is_not_siege_event(self):
        self.assertEqual([],self.adapter.parse([row(attackers=())],world=WORLD))

    def test_expired_siege_is_not_announced_as_future_registration(self):
        self.assertEqual([],self.adapter.parse([
            row(owner=None,siege_at=1000000000)
        ],world=WORLD))

    def test_named_owner_preserves_existing_semantics(self):
        event=self.adapter.parse([row(owner="Enemy")],world=WORLD)[0]
        self.assertEqual("Enemy",event.clan)
        self.assertIn("Owner: Enemy",event.body)

    def test_clan_filter_does_not_misclassify_npc_as_clan(self):
        event=self.adapter.parse([row(owner=None)],world=WORLD)[0]
        for target in (
            Subscription("channel",WORLD,clans=frozenset(("NPC",))),
            Subscription("channel",WORLD,clans=frozenset(("BSOE",))),
        ):
            with self.subTest(clans=target.clans):
                self.assertFalse(target.matches(event))
        self.assertTrue(Subscription("channel",WORLD).matches(event))


if __name__=="__main__":
    unittest.main()
