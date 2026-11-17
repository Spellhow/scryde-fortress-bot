"""Side-effect-free Scryde baseline and malformed-data shadow tests."""
import copy
import unittest

from community.adapters.scryde_shadow import inspect_scryde_ranking as inspect


def row(identifier, owner, *, name="Gludio Castle", attackers=(), siege_at=0):
    return {
        "id": identifier, "name": name,
        "owner": None if owner is None else {"name": owner},
        "siege_at": siege_at,
        "siege_sides": {"attackers": [{"name": name} for name in attackers]},
    }


def state(identifier=116, had=True):
    return {"objects": {str(identifier): {"had": had, "name": "Antharas Fortress", "id": identifier}}}


class ShadowTests(unittest.TestCase):
    def report(self, items, prev=None, typ="fortress"):
        return inspect(items, clan="BSOE", object_type=typ, previous_state=prev)

    def test_two_owned_objects_and_our_attack(self):
        rows = [row(116, "BSOE"), row(117, "BSOE"),
                row(118, "Other", attackers=("BSOE", "Enemy"))]
        result = self.report(rows)
        self.assertEqual(("116", "117"), result.owned_by_clan)
        self.assertEqual(("118",), result.attacks_by_clan)

    def test_absent_prior_owner_is_deferred(self):
        result = self.report([], state())
        self.assertEqual((), result.confirmed_owner_changes)
        self.assertEqual(("116",), result.missing_prior_owned)

    def test_owner_changes_on_explicit_row_only(self):
        result = self.report([row(116, "Enemy")], state())
        self.assertEqual(("116",), result.confirmed_owner_changes)
        self.assertEqual((), result.missing_prior_owned)

    def test_npc_owner_is_explicit_transition(self):
        result = self.report([row(116, None)], state())
        self.assertEqual(("116",), result.confirmed_owner_changes)

    def test_same_owner_is_not_transition(self):
        result = self.report([row(116, "BSOE")], state())
        self.assertEqual(("116",), result.owned_by_clan)
        self.assertEqual((), result.confirmed_owner_changes)

    def test_legacy_flat_state_is_understood(self):
        result = self.report([row(116, "Enemy")], {"id": 116, "had": True})
        self.assertEqual(("116",), result.confirmed_owner_changes)

    def test_invalid_rows_cannot_prove_loss(self):
        bad = [None, "invalid", {"id": 116}, {"id": 116, "name": "Fortress", "owner": "garbled"}]
        result = self.report(bad, state())
        self.assertEqual(("116",), result.missing_prior_owned)
        self.assertEqual(4, result.rejected_rows)
        self.assertEqual((), result.confirmed_owner_changes)

    def test_duplicate_rows_cannot_prove_loss(self):
        result = self.report([row(116, "Enemy"), row(116, "BSOE")], state())
        self.assertEqual(("116",), result.missing_prior_owned)
        self.assertEqual(1, result.duplicate_ids)

    def test_malformed_attackers_do_not_crash_or_infer_attack(self):
        item = row(116, "Enemy", attackers=("BSOE",))
        item["siege_sides"] = {"attackers": [{"name": 1}]}
        result = self.report([item], state())
        self.assertEqual(1, result.rejected_rows)
        self.assertEqual((), result.attacks_by_clan)

    def test_unchanged_state_and_input(self):
        prior=state()
        items=[row(116, "Enemy")]
        old_prior, old_items=copy.deepcopy(prior), copy.deepcopy(items)
        self.report(items, prior)
        self.assertEqual(old_prior, prior)
        self.assertEqual(old_items, items)

    def test_summary_carries_counts_only(self):
        result=self.report([row(116, "BSOE")], state())
        summary=str(result.summary())
        self.assertNotIn("BSOE", summary)
        self.assertNotIn("Gludio", summary)
        self.assertEqual(1,result.summary()["ours"])

    def test_no_network_or_publisher_imports(self):
        # It must remain importable using only Python stdlib.
        import community.adapters.scryde_shadow as shadow
        self.assertFalse(hasattr(shadow, "send_notification"))
        self.assertFalse(hasattr(shadow, "fetch_page_data"))


if __name__ == "__main__":
    unittest.main()
