"""Per-destination delivery attempts and unambiguous language selection."""
import unittest

from community.config import parse_config
from community.models import Destination, Event, Provenance, Subscription, World
from community.router import dispatch_events
from community.state import DeliveryState
from datetime import datetime, timezone

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
WORLD={"network":"Scryde","name":"x1000"}
WORLD_OBJECT=World("Scryde","x1000")


def fixture(destinations=None,subscriptions=None,sources=None):
    return parse_config({
        "version":1,
        "sources":sources or [
            {"id":"news","kind":"rss","url":"https://example.com/news","world":WORLD},
            {"id":"siege","kind":"rss","url":"https://example.com/siege","world":WORLD},
        ],
        "destinations":destinations if destinations is not None else [
            {"id":"clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}
        ],
        "subscriptions":subscriptions if subscriptions is not None else [
            {"destination_id":"clan","world":WORLD}
        ],
    })


def event(source="news",kind="news"):
    return Event(WORLD_OBJECT,source,"post-42",kind,"Update","Text",
                 "https://example.com/news",Provenance.OBSERVED,NOW)


class SubscriptionIsolationTests(unittest.TestCase):
    def test_failed_overlapping_subscription_attempts_only_once(self):
        target=Destination("clan","telegram","CHAT","TOKEN")
        subs=[Subscription("clan",WORLD_OBJECT),Subscription("clan",WORLD_OBJECT)]
        calls=[]
        state=DeliveryState()
        def fail(d,e,lang):
            calls.append(lang)
            return False
        first=dispatch_events([event()],subs,{"clan":target},state,fail,now=NOW)
        self.assertEqual((1,0,1),(first.attempted,first.sent,first.skipped))
        self.assertEqual(1,len(first.errors))
        self.assertEqual(["uk"],calls)
        self.assertFalse(state.was_delivered("clan",event().event_id))
        retried=dispatch_events([event()],subs,{"clan":target},state,
                                lambda d,e,lang:calls.append(lang) or True,now=NOW)
        self.assertEqual(1,retried.attempted)
        self.assertEqual(1,retried.sent)
        self.assertTrue(state.was_delivered("clan",event().event_id))
        again=dispatch_events([event()],subs,{"clan":target},state,
                              lambda *_:self.fail("already sent"),now=NOW)
        self.assertEqual(0,again.attempted)

    def test_first_success_no_duplicate_to_same_destination(self):
        target=Destination("clan","telegram","CHAT","TOKEN")
        subs=[Subscription("clan",WORLD_OBJECT),Subscription("clan",WORLD_OBJECT)]
        calls=[]
        outcome=dispatch_events([event()],subs,{"clan":target},DeliveryState(),
                                lambda dest,ev,lang:calls.append(dest.id) or True,now=NOW)
        self.assertEqual(["clan"],calls)
        self.assertEqual(1,outcome.sent)

    def test_different_destinations_both_attempt_even_if_first_failed(self):
        destinations={
            "one": Destination("one","telegram","CHAT_ONE","TOKEN"),
            "two": Destination("two","telegram","CHAT_TWO","TOKEN"),
        }
        subs=[Subscription("one",WORLD_OBJECT),Subscription("two",WORLD_OBJECT)]
        attempts=[]
        result=dispatch_events([event()],subs,destinations,DeliveryState(),
                               lambda d,e,l: attempts.append(d.id) or (d.id=="two"),now=NOW)
        self.assertEqual(["one","two"],attempts)
        self.assertEqual(2,result.attempted)
        self.assertEqual(1,result.sent)

    def test_same_casefold_destination_alias_rejected(self):
        dests=[
            {"id":"Clan","kind":"telegram","address_env":"CHAT_A","token_env":"TOKEN"},
            {"id":"clan","kind":"telegram","address_env":"CHAT_B","token_env":"TOKEN"},
        ]
        with self.assertRaises(ValueError):
            fixture(destinations=dests)

    def test_same_casefold_source_alias_rejected(self):
        sources=[
            {"id":"News","kind":"rss","url":"https://example.com/a","world":WORLD},
            {"id":"news","kind":"rss","url":"https://example.com/b","world":WORLD},
        ]
        with self.assertRaises(ValueError):
            fixture(sources=sources)

    def test_whitespace_aliases_rejected(self):
        with self.assertRaises(ValueError):
            fixture(destinations=[
                {"id":" clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}])
        with self.assertRaises(ValueError):
            fixture(sources=[
                {"id":" news ","kind":"rss","url":"https://example.com/news","world":WORLD}])

    def test_overlapping_language_preferences_rejected(self):
        subscriptions=[
            {"destination_id":"clan","world":WORLD,"language":"uk"},
            {"destination_id":"clan","world":WORLD,"language":"en"},
        ]
        with self.assertRaisesRegex(ValueError,"overlapping subscriptions"):
            fixture(subscriptions=subscriptions)

    def test_nonoverlap_by_source_language_allowed(self):
        subscriptions=[
            {"destination_id":"clan","world":WORLD,"language":"uk","source_ids":["news"]},
            {"destination_id":"clan","world":WORLD,"language":"en","source_ids":["siege"]},
        ]
        cfg=fixture(subscriptions=subscriptions)
        self.assertEqual(2,len(cfg.subscriptions))
        targets=[]
        dispatch_events([event("news"),event("siege")],cfg.subscriptions,cfg.destinations,
                        DeliveryState(),lambda d,e,lang: targets.append((e.source_id,lang)) or True,now=NOW)
        self.assertEqual([("news","uk"),("siege","en")],targets)

    def test_nonoverlap_by_kind_or_clan_allowed(self):
        subs=[
            {"destination_id":"clan","world":WORLD,"language":"uk","event_types":["news"]},
            {"destination_id":"clan","world":WORLD,"language":"en","event_types":["siege_registration"]},
        ]
        self.assertEqual(2,len(fixture(subscriptions=subs).subscriptions))
        subs[0].pop("event_types")
        subs[1].pop("event_types")
        subs[0]["clans"]=["BSOE"]
        subs[1]["clans"]=["OTHER"]
        self.assertEqual(2,len(fixture(subscriptions=subs).subscriptions))

    def test_limit_subscriptions_to_bounded_amount(self):
        subs=[{"destination_id":"clan","world":WORLD} for _ in range(101)]
        with self.assertRaisesRegex(ValueError,"too many"):
            fixture(subscriptions=subs)


if __name__ == "__main__":
    unittest.main()
