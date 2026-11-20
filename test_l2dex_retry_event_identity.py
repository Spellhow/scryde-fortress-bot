"""No receipt collision when L2Dex rankings change before failed sends retry.

The previous snapshot is intentionally retained on partial delivery, so
generation numbers alone cannot uniquely identify competing observations.
"""
from datetime import timedelta
import unittest

from community.adapters.l2dex import diff_castles, parse_castles, load_snapshot, state_key
from community.config import parse_config
from community.runner import run
from community.state import DeliveryState
from test_l2dex_adapter import NOW, SRC, WORLD, URL, castle_row, page


def configuration():
    world={
        "network":"L2Dex","name":"New-Interlude x25","chronicle":"Interlude"
    }
    return parse_config({
        "version":1,
        "sources":[{
            "id":"dex","kind":"l2dex_castles","world":world,"url":URL,
        }],
        "destinations":[
            {"id":"telegram","kind":"telegram",
             "address_env":"TG_CHAT","token_env":"TG_TOKEN"},
            {"id":"discord","kind":"discord","address_env":"WEBHOOK"},
        ],
        "subscriptions":[
            {"destination_id":"telegram","world":world},
            {"destination_id":"discord","world":world},
        ],
    })


def ranking(owner="Alpha", attackers="-", siege="29-11-26 16:00"):
    return page(castle_row(1,"Gludio Castle",owner,attacks=attackers,siege=siege))


class L2DexRetryEventIdentityTests(unittest.TestCase):
    def test_different_owners_same_generation_have_distinct_event_id(self):
        _,baseline=diff_castles(
            None,parse_castles(ranking()),SRC,NOW
        )
        b,_=diff_castles(
            baseline,parse_castles(ranking(owner="Beta")),SRC,NOW
        )
        c,_=diff_castles(
            baseline,parse_castles(ranking(owner="Gamma")),SRC,NOW
        )
        self.assertEqual(1,len(b))
        self.assertEqual(1,len(c))
        self.assertNotEqual(b[0].event_id,c[0].event_id)
        self.assertNotEqual(b[0].external_id,c[0].external_id)
        self.assertIn("castle:1:owner:1:",b[0].external_id)

    def test_same_owner_during_retry_has_stable_event_id(self):
        _,baseline=diff_castles(
            None,parse_castles(ranking()),SRC,NOW
        )
        first,_=diff_castles(
            baseline,parse_castles(ranking(owner="Beta")),SRC,NOW
        )
        later,_=diff_castles(
            baseline,parse_castles(ranking(owner="Beta",siege="01-12-26 14:00")),
            SRC,NOW+timedelta(minutes=20)
        )
        self.assertEqual(first[0].event_id,later[0].event_id)
        self.assertEqual(first[0].external_id,later[0].external_id)

    def test_different_attacker_sets_same_generation_are_distinct(self):
        _,baseline=diff_castles(None,parse_castles(ranking()),SRC,NOW)
        beta,_=diff_castles(baseline,parse_castles(ranking(attackers="Beta")),SRC,NOW)
        gamma,_=diff_castles(baseline,parse_castles(ranking(attackers="Gamma")),SRC,NOW)
        self.assertEqual("siege_registration",beta[0].kind)
        self.assertNotEqual(beta[0].event_id,gamma[0].event_id)
        self.assertIn("attack-registration:1:",beta[0].external_id)

    def test_owner_change_after_partial_delivery_reaches_both_channels(self):
        cfg=configuration()
        state=DeliveryState()
        run(cfg,state,fetch=lambda _:ranking(),
            send=lambda *_:self.fail("initial baseline only"),
            credentials={},now=NOW)
        key=state_key("dex",cfg.sources[0].world,URL)
        initial=state.cursors[key]
        deliveries=[]
        first=run(
            cfg,state,fetch=lambda _:ranking(owner="Beta"),
            send=lambda target,event,*_:
                deliveries.append((target.id,event.external_id)) or target.id=="telegram",
            credentials={},now=NOW+timedelta(minutes=20)
        )
        self.assertEqual(1,first.sent)
        self.assertEqual(1,len(first.errors))
        self.assertEqual(initial,state.cursors[key])
        self.assertEqual(2,len(deliveries))
        beta_event_id=deliveries[0][1]
        deliveries.clear()

        # Ranking changed *again* before the Discord retry. If only
        # generation number were used, TG would incorrectly skip Gamma.
        second=run(
            cfg,state,fetch=lambda _:ranking(owner="Gamma"),
            send=lambda target,event,*_:deliveries.append(
                (target.id,event.external_id)
            ) or True,
            credentials={},now=NOW+timedelta(minutes=40)
        )
        self.assertEqual(2,second.sent)
        self.assertEqual(0,len(second.errors))
        self.assertEqual(
            ["telegram","discord"],[target for target,_ in deliveries]
        )
        self.assertNotEqual(beta_event_id,deliveries[0][1])
        self.assertEqual("Gamma",load_snapshot(state.cursors[key])["1"]["owner"])
        final=run(
            cfg,state,fetch=lambda _:ranking(owner="Gamma"),
            send=lambda *_:self.fail("no same-owner duplicate"),
            credentials={},now=NOW+timedelta(minutes=60)
        )
        self.assertEqual(0,final.sent)

    def test_same_owner_retry_only_failed_destination(self):
        cfg=configuration()
        state=DeliveryState()
        run(cfg,state,fetch=lambda _:ranking(),send=lambda *_:True,
            credentials={},now=NOW)
        first=run(
            cfg,state,fetch=lambda _:ranking(owner="Beta"),
            send=lambda target,*_:target.id=="telegram",
            credentials={},now=NOW+timedelta(minutes=20)
        )
        self.assertEqual(1,first.sent)
        calls=[]
        retry=run(
            cfg,state,fetch=lambda _:ranking(owner="Beta"),
            send=lambda target,*_:calls.append(target.id) or True,
            credentials={},now=NOW+timedelta(minutes=40)
        )
        self.assertEqual(["discord"],calls)
        self.assertEqual(1,retry.sent)

    def test_different_attack_registration_after_failed_delivery_not_suppressed(self):
        cfg=configuration()
        state=DeliveryState()
        run(cfg,state,fetch=lambda _:ranking(attackers="-"),
            send=lambda *_:True,credentials={},now=NOW)
        first=run(
            cfg,state,fetch=lambda _:ranking(attackers="Beta"),
            send=lambda target,*_:target.id=="telegram",
            credentials={},now=NOW+timedelta(minutes=20)
        )
        self.assertEqual(1,first.sent)
        calls=[]
        second=run(
            cfg,state,fetch=lambda _:ranking(attackers="Gamma"),
            send=lambda target,event,*_:calls.append(
                (target.id,event.external_id)
            ) or True,
            credentials={},now=NOW+timedelta(minutes=40)
        )
        self.assertEqual(2,second.sent)
        self.assertEqual(
            ["telegram","discord"],[target for target,_ in calls]
        )
        self.assertIn("attack-registration:1:",calls[0][1])
        key=state_key("dex",cfg.sources[0].world,URL)
        self.assertEqual(["Gamma"],load_snapshot(state.cursors[key])["1"]["attackers"])


if __name__=="__main__":
    unittest.main()
