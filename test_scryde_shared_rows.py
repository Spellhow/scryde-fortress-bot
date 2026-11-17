"""Shared Scryde row trust boundary across legacy-compatible adapters."""
import copy
import unittest

from community.adapters.scryde_rows import (
    is_valid_scryde_ranking_row, valid_scryde_ranking_rows, get_attackers
)
from community.adapters.scryde_shadow import inspect_scryde_ranking
from community.adapters.scryde import ScrydeRankingAdapter
from community.models import World

FUTURE=2000000000


def row(identifier=116, owner="BSOE", attackers=("Enemy",), siege_at=FUTURE):
    return {
        "id": identifier,
        "name": "Antharas Fortress",
        "owner": {"name": owner} if owner is not None else None,
        "siege_sides": {"attackers":[{"name":name} for name in attackers]},
        "siege_at": siege_at,
    }


class SharedScrydeRowsTests(unittest.TestCase):
    def test_explicit_npc_owner_valid_but_missing_owner_not_valid(self):
        self.assertTrue(is_valid_scryde_ranking_row(row(owner=None)))
        invalid=row()
        invalid.pop("owner")
        self.assertFalse(is_valid_scryde_ranking_row(invalid))

    def test_untrusted_owner_does_not_trigger_shadow_loss(self):
        invalid=row(owner="Enemy")
        invalid["owner"]="not a valid owner object"
        report=inspect_scryde_ranking(
            [invalid],clan="BSOE",object_type="fortress",
            previous_state={"objects":{"116":{"had":True}}},
        )
        self.assertEqual((),report.confirmed_owner_changes)
        self.assertEqual(("116",),report.missing_prior_owned)

    def test_valid_owner_change_is_only_an_observation(self):
        report=inspect_scryde_ranking(
            [row(owner="Enemy")],clan="BSOE",object_type="fortress",
            previous_state={"objects":{"116":{"had":True}}},
        )
        self.assertEqual(("116",),report.confirmed_owner_changes)
        self.assertEqual((),report.missing_prior_owned)

    def test_invalid_sides_and_missing_row_are_rejected_consistently(self):
        bad=row()
        bad["siege_sides"]={"attackers":"string-not-list"}
        self.assertFalse(is_valid_scryde_ranking_row(bad))
        validated,count=valid_scryde_ranking_rows([bad,row(identifier=117)])
        self.assertEqual(1,count)
        self.assertEqual([117],[item["id"] for item in validated])

    def test_duplicate_ids_are_quarantined_not_choose_first(self):
        records,count=valid_scryde_ranking_rows([
            row(116,owner="BSOE"),row(116,owner="Enemy"),row(117)
        ])
        self.assertEqual(1,count)
        self.assertEqual([117],[item["id"] for item in records])

    def test_attacker_names_are_read_without_mutating_input(self):
        source=row(116,attackers=("BSOE","Enemy"))
        original=copy.deepcopy(source)
        names=get_attackers(source)
        self.assertEqual(["BSOE","Enemy"],names)
        self.assertEqual(original,source)

    def test_new_adapter_does_not_create_events_from_invalid_rows(self):
        adapter=ScrydeRankingAdapter("scryde-fortress","https://example.invalid")
        invalid=row()
        invalid.pop("owner")
        events=adapter.parse(
            [invalid,row(identifier=116,owner="Enemy",attackers=("BSOE",))],
            world=World("Scryde","x1000"),
        )
        self.assertEqual(1,len(events))
        self.assertEqual("siege_registration",events[0].kind)
        self.assertIn("BSOE",events[0].body)

    def test_new_adapter_does_not_emit_duplicate_conflicting_rows(self):
        adapter=ScrydeRankingAdapter("scryde-fortress","https://example.invalid")
        events=adapter.parse(
            [row(identifier=116,owner="Enemy"),row(identifier=116,owner="BSOE")],
            world=World("Scryde","x1000"),
        )
        self.assertEqual([],events)

    def test_legacy_validator_accepts_missing_siege_sides(self):
        item=row()
        item.pop("siege_sides")
        self.assertTrue(is_valid_scryde_ranking_row(item))
        self.assertEqual([],get_attackers(item))


if __name__ == "__main__":
    unittest.main()
