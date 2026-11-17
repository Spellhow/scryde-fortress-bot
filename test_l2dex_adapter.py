"""Offline L2Dex castle fixture, state-transition and delivery regression."""
import json
from datetime import datetime, timezone
import unittest

from community.adapters.l2dex import (
    parse_castles, diff_castles, load_snapshot, state_key,
)
from community.config import SourceConfig, parse_config
from community.models import World, Provenance
from community.state import DeliveryState

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
WORLD = World("L2Dex", "New-Interlude x25", "Interlude")
URL = "https://lineage2dex.com/en/rating/new-interlude.343"
SRC = SourceConfig("dex-new-interlude", "l2dex_castles", WORLD, URL)


def castle_row(number, name, owner, attacks="-", defenders="-", siege="29-11-26 16:00"):
    # Structure was checked against the L2Dex public ranking on 2026-11-17.
    return f"""<tr><th scope="row">{number}</th>
    <td><img src="/images/castle.jpg"></td>
    <td>{name}</td><td><p><strong>Tax:</strong>&nbsp; 15%<br>
    <strong>Clan:</strong>&nbsp; {owner}<br><strong>Leader:</strong>&nbsp; GuildLead</p></td>
    <td>{siege}</td><td class="hidden-xs" colspan="2"><p><small>
    <strong>Attackers:</strong> {attacks}</small><br><small>
    <strong>Defenders:</strong> {defenders}</small></p></td></tr>"""


def page(*rows):
    header = "<tr><th>ID</th><th>Picture</th><th>Name</th><th>Info</th><th>Date</th><th>Siege</th></tr>"
    return ('<table><tr><td>unrelated</td></tr></table>'
            '<div id="tab-top_castle"><table><thead>' + header +
            '</thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def state(events, snapshot):
    return load_snapshot(snapshot)


class CastleFixtureTests(unittest.TestCase):
    def test_real_layout_and_two_castles(self):
        parsed = parse_castles(page(
            castle_row(1, "Gludio Castle", "GhostRiders"),
            castle_row(3, "Giran Castle", "MartialKillers", "Rebels, Guardians",
                       defenders="MartialKillers"),
        ))
        self.assertEqual({"1", "3"}, set(parsed))
        self.assertEqual("GhostRiders", parsed["1"].owner)
        self.assertEqual(("Guardians", "Rebels"), parsed["3"].attackers)
        self.assertEqual("29-11-26 16:00", parsed["3"].siege_display)

    def test_missing_section_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_castles('<table><tr><td>invalid</td></tr></table>')

    def test_changed_headers_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_castles(page(castle_row(1, "Gludio Castle", "Old")).replace("<th>Siege</th>", "<th>Stats</th>"))

    def test_zero_castles_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_castles(page('<tr><td>garbled</td></tr>'))

    def test_duplicate_castle_id_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_castles(page(castle_row(1,"Gludio Castle","A"),castle_row(1,"Dion Castle","B")))

    def test_first_snapshot_has_no_notifications(self):
        castles = parse_castles(page(castle_row(1,"Gludio Castle","ClanA", "ClanB")))
        events, snap = diff_castles(None, castles, SRC, NOW)
        self.assertEqual([], events)
        self.assertEqual("ClanA", load_snapshot(snap)["1"]["owner"])

    def test_owner_change_event_only_if_both_owners_observed(self):
        baseline = parse_castles(page(castle_row(1,"Gludio Castle","ClanA")))
        _, old = diff_castles(None, baseline, SRC, NOW)
        changed = parse_castles(page(castle_row(1,"Gludio Castle","ClanB")))
        events, saved = diff_castles(old, changed, SRC, NOW)
        self.assertEqual(["castle_owner_change"],[x.kind for x in events])
        self.assertEqual(Provenance.OBSERVED, events[0].provenance)
        self.assertEqual(None, events[0].occurs_at)
        self.assertIn("timezone not specified", events[0].body)
        self.assertEqual("ClanB",load_snapshot(saved)["1"]["owner"])
        self.assertEqual([], diff_castles(saved, changed, SRC, NOW)[0])

    def test_return_to_prior_owner_still_emits_event(self):
        a = parse_castles(page(castle_row(1, "Gludio Castle", "A")))
        b = parse_castles(page(castle_row(1, "Gludio Castle", "B")))
        _, snap_a = diff_castles(None, a, SRC, NOW)
        first, snap_b = diff_castles(snap_a, b, SRC, NOW)
        second, _ = diff_castles(snap_b, a, SRC, NOW)
        self.assertNotEqual(first[0].event_id, second[0].event_id)

    def test_blank_owner_never_implies_loss(self):
        a = parse_castles(page(castle_row(1,"Gludio Castle","A")))
        _, snap = diff_castles(None,a,SRC,NOW)
        no_owner = parse_castles(page(castle_row(1,"Gludio Castle","")))
        events, snap2 = diff_castles(snap,no_owner,SRC,NOW)
        self.assertEqual([],events)
        self.assertEqual("A", load_snapshot(snap2)["1"]["owner"])

    def test_dash_placeholder_owner_does_not_trigger_false_transfer(self):
        original = parse_castles(page(castle_row(1, "Gludio Castle", "ClanA")))
        _, snapshot = diff_castles(None, original, SRC, NOW)
        placeholder = parse_castles(page(castle_row(1, "Gludio Castle", "-")))
        events, updated = diff_castles(snapshot, placeholder, SRC, NOW)
        self.assertEqual([], events)
        self.assertEqual("ClanA", load_snapshot(updated)["1"]["owner"])

    def test_missing_row_does_not_delete_prior_owner(self):
        a = parse_castles(page(castle_row(1,"Gludio Castle","A"),castle_row(2,"Dion Castle","B")))
        _, snap = diff_castles(None,a,SRC,NOW)
        missing = parse_castles(page(castle_row(2,"Dion Castle","B")))
        events, snap2 = diff_castles(snap,missing,SRC,NOW)
        self.assertEqual([],events)
        self.assertEqual("A",load_snapshot(snap2)["1"]["owner"])

    def test_attack_registration_and_reregistration(self):
        before = parse_castles(page(castle_row(1,"Gludio Castle","A","-")))
        new_attack = parse_castles(page(castle_row(1,"Gludio Castle","A","ClanB, ClanC")))
        _, snap = diff_castles(None,before,SRC,NOW)
        events, snap2 = diff_castles(snap,new_attack,SRC,NOW)
        self.assertEqual(1,len(events))
        self.assertEqual("siege_registration",events[0].kind)
        self.assertIn("registration, not a live attack", events[0].body)
        self.assertEqual([],diff_castles(snap2,new_attack,SRC,NOW)[0])
        cleared = parse_castles(page(castle_row(1,"Gludio Castle","A","-")))
        _, snap3 = diff_castles(snap2,cleared,SRC,NOW)
        again, _ = diff_castles(snap3,new_attack,SRC,NOW)
        self.assertNotEqual(events[0].event_id,again[0].event_id)

    def test_source_validation_rejects_wrong_domain_world_url(self):
        for url in (
            "https://evil.example/en/rating/new-interlude.343",
            "https://lineage2dex.com/en/rating/new-interlude.343?redirect=x",
            "https://lineage2dex.com/en/other",
        ):
            with self.subTest(url=url),self.assertRaises(ValueError):
                SourceConfig("dex","l2dex_castles",WORLD,url)

    def test_bad_stored_state_fails_closed(self):
        with self.assertRaises(ValueError):
            load_snapshot('{"version":2,"castles":{}}')

    def test_same_world_new_ranking_url_has_independent_baseline(self):
        self.assertNotEqual(
            state_key(SRC.id, WORLD, "https://lineage2dex.com/en/rating/new-interlude.343"),
            state_key(SRC.id, WORLD, "https://lineage2dex.com/en/rating/new-interlude.344"),
        )

    def test_different_worlds_use_different_state_cursors(self):
        self.assertNotEqual(state_key(SRC.id, WORLD),state_key(SRC.id,World("L2Dex","Skadi x100")))


if __name__ == "__main__":
    unittest.main()
