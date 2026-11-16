"""Offline end-to-end feed workflow without real network or credentials."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from community.config import parse_config
from community.runner import run
from community.state import DeliveryState
from community.models import World

NOW = datetime(2026,11,16,12,tzinfo=timezone.utc)
NEWS = '<rss><channel><item><guid>post-42</guid><title>Patch notes</title><description>Update details</description><link>https://example.com/p</link></item></channel></rss>'
NEWS_NEXT = NEWS.replace("post-42", "post-43").replace("Patch notes", "New event").replace("Update details", "Event details")


def build_config():
    world = {"network":"Scryde", "name":"x1000"}
    return parse_config({
        "version":1,
        "sources":[{"id":"feed","kind":"rss","world":world, "url":"https://example.com/feed", "enabled":True}],
        "destinations":[
            {"id":"alpha","kind":"telegram","address_env":"CHAT_A","token_env":"BOT_TOKEN"},
            {"id":"beta","kind":"discord","address_env":"DISCORD_WEBHOOK"},
        ],
        "subscriptions":[
            {"destination_id":"alpha","world":world,"source_ids":["feed"],"event_types":["news"]},
            {"destination_id":"beta","world":world,"source_ids":["feed"],"event_types":["news"]},
        ],
    })


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = build_config()

    def test_first_run_warm_start_and_new_events(self):
        state = DeliveryState()
        calls = []
        sender = lambda d,e,l,c: calls.append((d.id,e.external_id)) or True
        first = run(self.cfg,state,fetch=lambda _:NEWS,send=sender,credentials={},now=NOW)
        self.assertEqual(2,first.subscriptions_initialized)
        self.assertEqual(0,first.sent)
        self.assertEqual([],calls)
        # Existing post skipped, new article to both destinations.
        result = run(self.cfg,state,fetch=lambda _:NEWS.replace("</channel>","<item><guid>post-43</guid><title>Event</title><description>Details</description><link>https://example.com/e</link></item></channel>"),
                     send=sender,credentials={},now=NOW)
        self.assertEqual(2,result.sent)
        self.assertEqual([("alpha","post-43"),("beta","post-43")],calls)
        rerun = run(self.cfg,state,fetch=lambda _:NEWS.replace("</channel>","<item><guid>post-43</guid><title>Event</title><description>Details</description><link>https://example.com/e</link></item></channel>"),
                    send=sender,credentials={},now=NOW)
        self.assertEqual(0,rerun.sent)

    def test_failed_delivery_retried_for_one_destination(self):
        state = DeliveryState()
        run(self.cfg,state,fetch=lambda _:NEWS,send=lambda *args: True,credentials={},now=NOW)
        next_feed = NEWS.replace("post-42","post-44")
        calls = []
        def flaky(dest,event,lang,creds):
            calls.append(dest.id)
            return dest.id == "alpha"
        result = run(self.cfg,state,fetch=lambda _:next_feed,send=flaky,credentials={},now=NOW)
        self.assertEqual(1,result.sent)
        self.assertEqual(1,len(result.errors))
        retried = run(self.cfg,state,fetch=lambda _:next_feed,send=lambda *args:True,credentials={},now=NOW)
        self.assertEqual(1,retried.sent)

    def test_dry_run_never_sends_or_mutates_state(self):
        state = DeliveryState()
        result = run(self.cfg,state,fetch=lambda _:NEWS,
                     send=lambda *args: self.fail("must not send"),credentials={},now=NOW,dry_run=True)
        self.assertEqual(0,result.sent)
        self.assertEqual({},state.delivered)
        self.assertEqual({},state.cursors)

    def test_one_fetch_for_two_destinations(self):
        state = DeliveryState()
        requests = []
        def fetch(url):
            requests.append(url)
            return NEWS
        run(self.cfg,state,fetch=fetch,send=lambda *args:True,credentials={},now=NOW)
        self.assertEqual(["https://example.com/feed"],requests)

    def test_bad_source_does_not_block_another(self):
        world = {"network":"Scryde","name":"x1000"}
        config = parse_config({
            "version":1,
            "sources":[
                {"id":"broken","kind":"rss","url":"https://example.com/bad","world":world},
                {"id":"good","kind":"rss","url":"https://example.com/good","world":world},
            ],
            "destinations":[{"id":"a","kind":"telegram","address_env":"CHAT_A","token_env":"BOT_TOKEN"}],
            "subscriptions":[{"destination_id":"a","world":world}],
        })
        state=DeliveryState()
        calls=[]
        def fetch(url):
            calls.append(url)
            if url.endswith("/bad"): raise RuntimeError("credential leakage forbidden")
            return NEWS
        result=run(config,state,fetch=fetch,send=lambda *args:True,credentials={},now=NOW)
        self.assertEqual(2,len(calls))
        self.assertEqual(1,len(result.errors))
        self.assertNotIn("credential leakage forbidden",str(result.errors))

    def test_initialization_state_roundtrip(self):
        state=DeliveryState()
        run(self.cfg,state,fetch=lambda _:NEWS,send=lambda *args:True,credentials={},now=NOW)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"state.json"
            state.save(path)
            second=DeliveryState.load(path)
            self.assertEqual(2,len(second.cursors))


if __name__ == "__main__":
    unittest.main()
