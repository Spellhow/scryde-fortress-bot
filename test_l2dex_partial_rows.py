"""Incomplete public L2Dex data must not invent new siege registrations.

Uses static official-layout fixtures; no network, tokens or live messages.
"""
from datetime import timedelta
import unittest

from community.adapters.l2dex import parse_castles, diff_castles, load_snapshot, state_key
from community.runner import run
from community.config import parse_config
from community.state import DeliveryState
from community.source_health import SourceHealth
from test_l2dex_adapter import castle_row, page, NOW, SRC, WORLD, URL


def without_attackers(html):
    return html.replace("<strong>Attackers:</strong>", "<strong>Unavailable:</strong>")


def without_clan(html):
    return html.replace("<strong>Clan:</strong>", "<strong>Unavailable:</strong>")


class PartialRankingRowsTests(unittest.TestCase):
    def test_missing_attackers_label_skips_only_incomplete_row(self):
        first=castle_row(1,"Gludio Castle","Alpha",attacks="Beta")
        second=castle_row(2,"Dion Castle","Stable",attacks="Gamma")
        parsed=parse_castles(page(without_attackers(first),second))
        self.assertEqual({"2"},set(parsed))
        self.assertEqual(("Gamma",),parsed["2"].attackers)

    def test_missing_clan_label_is_not_observed_owner(self):
        source=page(
            without_clan(castle_row(1,"Gludio Castle","Unknown",attacks="Beta")),
            castle_row(2,"Dion Castle","Gamma"),
        )
        self.assertEqual({"2"},set(parse_castles(source)))

    def test_all_missing_labels_fail_closed_not_empty_success(self):
        for tamper in (without_attackers,without_clan):
            with self.subTest(tamper=tamper.__name__),self.assertRaises(ValueError):
                parse_castles(page(tamper(castle_row(
                    1,"Gludio Castle","Alpha",attacks="Beta"
                ))))

    def test_reappearance_after_partial_html_does_not_make_fake_attack(self):
        full=page(
            castle_row(1,"Gludio Castle","Alpha",attacks="Beta"),
            castle_row(2,"Dion Castle","Gamma",attacks="-"),
        )
        partial=page(
            without_attackers(castle_row(1,"Gludio Castle","Alpha",attacks="Beta")),
            castle_row(2,"Dion Castle","Gamma",attacks="-"),
        )
        _,original=diff_castles(None,parse_castles(full),SRC,NOW)
        observed,unchanged=diff_castles(original,parse_castles(partial),SRC,NOW)
        self.assertEqual([],observed)
        self.assertEqual(("Beta",),tuple(load_snapshot(unchanged)["1"]["attackers"]))
        later,restored=diff_castles(unchanged,parse_castles(full),SRC,NOW)
        self.assertEqual([],later)
        self.assertEqual(("Beta",),tuple(load_snapshot(restored)["1"]["attackers"]))

    def test_legitimate_explicit_clear_and_reregister_still_emits(self):
        registered=page(castle_row(1,"Gludio Castle","Alpha",attacks="Beta"))
        removed=page(castle_row(1,"Gludio Castle","Alpha",attacks="-"))
        _,before=diff_castles(None,parse_castles(registered),SRC,NOW)
        _,cleared=diff_castles(before,parse_castles(removed),SRC,NOW)
        self.assertEqual([],load_snapshot(cleared)["1"]["attackers"])
        alerts,after=diff_castles(cleared,parse_castles(registered),SRC,NOW)
        self.assertEqual(["siege_registration"],[item.kind for item in alerts])
        self.assertEqual(["Beta"],load_snapshot(after)["1"]["attackers"])

    def test_valid_other_castle_owner_change_remains_observable(self):
        initial=page(
            castle_row(1,"Gludio Castle","Alpha",attacks="Beta"),
            castle_row(2,"Dion Castle","Gamma"),
        )
        next_page=page(
            without_attackers(castle_row(1,"Gludio Castle","Alpha",attacks="Beta")),
            castle_row(2,"Dion Castle","Delta"),
        )
        _,before=diff_castles(None,parse_castles(initial),SRC,NOW)
        changes,after=diff_castles(before,parse_castles(next_page),SRC,NOW)
        self.assertEqual(["castle_owner_change"],[event.kind for event in changes])
        self.assertEqual("2",changes[0].external_id.split(":")[1])
        self.assertEqual("Alpha",load_snapshot(after)["1"]["owner"])

    def test_runner_backoff_all_partial_rows_keeps_prior_snapshot(self):
        cfg=parse_config({
            "version":1,
            "sources":[{
                "id":"dex","kind":"l2dex_castles","url":URL,
                "world":{
                    "network":"L2Dex","name":"New-Interlude x25",
                    "chronicle":"Interlude"
                },
            }],
            "destinations":[{"id":"alpha","kind":"telegram",
                             "address_env":"CHANNEL","token_env":"TOKEN"}],
            "subscriptions":[{"destination_id":"alpha",
                              "world":{
                                  "network":"L2Dex","name":"New-Interlude x25",
                                  "chronicle":"Interlude"
                              }}],
        })
        baseline=page(castle_row(1,"Gludio Castle","Alpha",attacks="Beta"))
        broken=page(without_attackers(castle_row(
            1,"Gludio Castle","Alpha",attacks="Beta"
        )))
        state=DeliveryState()
        run(cfg,state,fetch=lambda _:baseline,
            send=lambda *_:self.fail("baseline is silent"),credentials={},now=NOW)
        key=state_key(cfg.sources[0].id,cfg.sources[0].world,URL)
        before=state.cursors[key]
        errors=run(cfg,state,fetch=lambda _:broken,
                   send=lambda *_:self.fail("bad markup must not publish"),
                   credentials={},now=NOW+timedelta(minutes=1))
        self.assertEqual(1,len(errors.errors))
        self.assertEqual(before,state.cursors[key])
        defer=run(cfg,state,fetch=lambda *_:self.fail("must back off"),
                  send=lambda *_:self.fail("cannot send"),
                  credentials={},now=NOW+timedelta(minutes=4))
        self.assertEqual(1,defer.deferred_sources)
        fixed=run(cfg,state,fetch=lambda _:baseline,
                  send=lambda *_:self.fail("same registration not new"),
                  credentials={},now=NOW+timedelta(minutes=21))
        self.assertEqual(0,fixed.sent)
        self.assertEqual(0,len(fixed.errors))
        self.assertEqual(before,state.cursors[key])


if __name__=="__main__":
    unittest.main()
