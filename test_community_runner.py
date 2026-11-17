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

    def test_l2dex_retries_only_failed_destination_and_preserves_snapshot(self):
        from test_l2dex_adapter import page, castle_row, NOW
        world = {"network": "L2Dex", "name": "New-Interlude x25", "chronicle": "Interlude"}
        config = parse_config({
            "version": 1,
            "sources": [{
                "id": "l2dex", "kind": "l2dex_castles",
                "url": "https://lineage2dex.com/en/rating/new-interlude.343",
                "world": world,
            }],
            "destinations": [
                {"id": "alpha", "kind": "telegram", "address_env": "CHAT_A", "token_env": "BOT_TOKEN"},
                {"id": "beta", "kind": "discord", "address_env": "DISCORD_WEBHOOK"},
            ],
            "subscriptions": [
                {"destination_id": "alpha", "world": world},
                {"destination_id": "beta", "world": world},
            ],
        })
        initial = page(castle_row(1, "Gludio Castle", "ClanA"))
        changed = page(castle_row(1, "Gludio Castle", "ClanB", "ClanC"))
        state = DeliveryState()
        first = run(config, state, fetch=lambda _: initial, send=lambda *args: True,
                    credentials={}, now=NOW)
        self.assertEqual(0, first.sent)
        cursor_before = dict(state.cursors)
        attempts = []

        def flaky(dest, event, lang, secrets):
            attempts.append(dest.id)
            return dest.id == "alpha"

        result = run(config, state, fetch=lambda _: changed, send=flaky,
                     credentials={}, now=NOW)
        self.assertEqual(2, result.sent)
        self.assertEqual(2, len(result.errors))
        self.assertEqual(cursor_before.get(next(k for k in cursor_before if k.startswith("l2dex-castles:"))),
                         state.cursors[next(k for k in cursor_before if k.startswith("l2dex-castles:"))])
        repaired = run(config, state, fetch=lambda _: changed, send=lambda *args: True,
                       credentials={}, now=NOW)
        self.assertEqual(2, repaired.sent)
        self.assertEqual(0, len(repaired.errors))
        repeat = run(config, state, fetch=lambda _: changed, send=lambda *args: True,
                     credentials={}, now=NOW)
        self.assertEqual(0, repeat.sent)

    def test_l2dex_missing_table_does_not_reset_state(self):
        from test_l2dex_adapter import page, castle_row, NOW
        world = {"network": "L2Dex", "name": "New-Interlude x25"}
        conf = parse_config({
            "version": 1,
            "sources": [{"id": "l2dex", "kind": "l2dex_castles",
                         "url": "https://lineage2dex.com/en/rating/new-interlude.343", "world": world}],
            "destinations": [{"id": "a", "kind": "telegram", "address_env": "CHAT_A", "token_env": "BOT_TOKEN"}],
            "subscriptions": [{"destination_id": "a", "world": world}],
        })
        state = DeliveryState()
        run(conf, state, fetch=lambda _: page(castle_row(1, "Gludio Castle", "A")),
            send=lambda *args: True, credentials={}, now=NOW)
        before = dict(state.cursors)
        failed = run(conf, state, fetch=lambda _: "<html>challenge</html>",
                     send=lambda *args: self.fail("must not publish"), credentials={}, now=NOW)
        self.assertEqual(1, len(failed.errors))
        self.assertEqual(before, state.cursors)

    def test_manual_reminder_without_network_and_no_repeat(self):
        from datetime import timedelta
        world = {"network":"Scryde", "name":"x1000"}
        scheduled = parse_config({
            "version": 1, "sources": [],
            "scheduled_events": [{
                "id": "community-meetup", "world": world,
                "title": "Clan meeting", "body": "Meet the clan",
                "starts_at": (NOW + timedelta(minutes=60)).isoformat(),
                "remind_before_minutes": [60],
            }],
            "destinations": [
                {"id":"a", "kind":"telegram", "address_env":"CHAT_A", "token_env":"BOT_TOKEN"},
                {"id":"b", "kind":"discord", "address_env":"DISCORD_WEBHOOK"},
            ],
            "subscriptions": [
                {"destination_id":"a", "world":world, "source_ids":["manual_schedule"]},
                {"destination_id":"b", "world":world, "source_ids":["manual_schedule"]},
            ]
        })
        state = DeliveryState()
        calls = []
        def send(target, event, lang, credentials):
            calls.append(target.id)
            return True
        first = run(scheduled, state, fetch=lambda *_: self.fail("schedule must not fetch"),
                    send=send, credentials={}, now=NOW)
        self.assertEqual((0, 2), (first.sources_checked, first.sent))
        self.assertEqual(["a", "b"], calls)
        repeat = run(scheduled, state, fetch=lambda *_: self.fail("unexpected fetch"),
                     send=send, credentials={}, now=NOW)
        self.assertEqual(0, repeat.sent)

    def test_manual_reminder_failed_delivery_is_retriable(self):
        from datetime import timedelta
        world = {"network":"Scryde", "name":"x1000"}
        scheduled = parse_config({
            "version": 1, "sources": [],
            "scheduled_events": [{
                "id": "weekly-meeting", "world": world,
                "title": "Community meeting", "body": "Join us",
                "starts_at": (NOW + timedelta(minutes=60)).isoformat(),
                "remind_before_minutes": [60],
            }],
            "destinations": [
                {"id":"a","kind":"telegram","address_env":"CHAT_A","token_env":"BOT_TOKEN"},
                {"id":"b","kind":"telegram","address_env":"CHAT_B","token_env":"BOT_TOKEN"},
            ],
            "subscriptions": [
                {"destination_id":"a","world":world},
                {"destination_id":"b","world":world},
            ]
        })
        state = DeliveryState()
        first = run(scheduled, state,
                    fetch=lambda *_: self.fail("network"),
                    send=lambda target, *_: target.id == "a",
                    credentials={}, now=NOW)
        self.assertEqual(1, first.sent)
        self.assertEqual(1, len(first.errors))
        again = run(scheduled, state,
                    fetch=lambda *_: self.fail("network"),
                    send=lambda *args: True,
                    credentials={}, now=NOW)
        self.assertEqual(1, again.sent)

    def test_shared_public_feed_two_worlds_fetched_once_with_isolated_keywords(self):
        config = parse_config({
            "version": 1,
            "sources": [
                {"id":"scryde100","kind":"rss","world":{"network":"Scryde","name":"x100"},
                 "url":"https://example.com/news","include_keywords":["x100"]},
                {"id":"scryde1000","kind":"rss","world":{"network":"Scryde","name":"x1000"},
                 "url":"https://example.com/news","include_keywords":["x1000"]},
            ],
            "destinations":[
                {"id":"low","kind":"telegram","address_env":"CHAT_LOW","token_env":"TOKEN"},
                {"id":"high","kind":"telegram","address_env":"CHAT_HIGH","token_env":"TOKEN"},
            ],
            "subscriptions":[
                {"destination_id":"low","world":{"network":"Scryde","name":"x100"}},
                {"destination_id":"high","world":{"network":"Scryde","name":"x1000"}},
            ],
        })
        def payload(items):
            return "<rss><channel>" + "".join(
                f"<item><guid>{ident}</guid><title>{title}</title><description>{title} info</description>"
                f"<link>https://example.com/{ident}</link></item>"
                for ident,title in items
            ) + "</channel></rss>"
        state=DeliveryState()
        calls=[]
        requests=[]
        def fetch(url):
            requests.append(url)
            return payload([("1","News x100"),("2","News x1000")])
        first=run(config,state,fetch=fetch,send=lambda *args: True,credentials={},now=NOW)
        self.assertEqual(0,first.sent)
        self.assertEqual(1,len(requests))
        self.assertEqual(2,len(state.cursors))
        requests.clear()
        def fetch_next(url):
            requests.append(url)
            return payload([
                ("1","News x100"),("2","News x1000"),("3","x100 upcoming event"),
                ("4","x1000 upcoming event"),
            ])
        result=run(config,state,fetch=fetch_next,
                   send=lambda dest,event,*_:calls.append((dest.id,event.external_id)) or True,
                   credentials={},now=NOW)
        self.assertEqual(2,result.sent)
        self.assertEqual([("low","3"),("high","4")],calls)
        self.assertEqual(1,len(requests))

    def test_shared_failed_source_url_is_not_refetched_or_exposed(self):
        worlds = [
            {"network":"Scryde","name":"x100"},
            {"network":"Scryde","name":"x1000"},
        ]
        config=parse_config({
            "version":1,
            "sources":[
                {"id":"s1","kind":"rss","url":"https://example.com/news","world":worlds[0]},
                {"id":"s2","kind":"rss","url":"https://example.com/news","world":worlds[1]},
            ],
            "destinations":[{"id":"clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}],
            "subscriptions":[{"destination_id":"clan","world":worlds[0]}],
        })
        requests=[]
        def fail(url):
            requests.append(url)
            raise RuntimeError("private credential must not reach logs")
        state=DeliveryState()
        result=run(config,state,fetch=fail,
                   send=lambda *args: self.fail("delivery never runs"),
                   credentials={},now=NOW)
        self.assertEqual(1,len(requests))
        self.assertEqual(2,len(result.errors))
        self.assertNotIn("private credential",str(result.errors))
        self.assertEqual({},state.delivered)

    def test_adjusting_source_keywords_restarts_baseline_silently(self):
        from copy import deepcopy
        baseline = parse_config({
            "version":1,
            "sources":[{"id":"feed","kind":"rss","world":{"network":"Scryde","name":"x1000"},
                        "url":"https://example.com/feed","include_keywords":["x1000"]}],
            "destinations":[{"id":"clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}],
            "subscriptions":[{"destination_id":"clan","world":{"network":"Scryde","name":"x1000"}}],
        })
        state = DeliveryState()
        rss='<rss><channel><item><guid>1</guid><title>x1000 patch</title><description>x1000 update</description><link>https://example.com/1</link></item></channel></rss>'
        run(baseline,state,fetch=lambda _:rss,send=lambda *args:True,credentials={},now=NOW)
        modified = parse_config({
            "version":1,
            "sources":[{"id":"feed","kind":"rss","world":{"network":"Scryde","name":"x1000"},
                        "url":"https://example.com/feed","include_keywords":["patch"]}],
            "destinations":[{"id":"clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}],
            "subscriptions":[{"destination_id":"clan","world":{"network":"Scryde","name":"x1000"}}],
        })
        sent=[]
        updated=run(modified,state,fetch=lambda _:rss,
                    send=lambda *args:sent.append(1) or True,credentials={},now=NOW)
        self.assertEqual(0,updated.sent)
        self.assertEqual([],sent)

    def test_feed_url_change_warms_new_archive_without_backlog(self):
        world={"network":"Scryde","name":"x1000"}
        def config(url):
            return parse_config({
                "version":1,
                "sources":[{"id":"feed","kind":"rss","url":url,"world":world}],
                "destinations":[{"id":"clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}],
                "subscriptions":[{"destination_id":"clan","world":world}],
            })
        def rss(*ids):
            return "<rss><channel>" + "".join(
                "<item><guid>post-{0}</guid><title>News {0}</title>"
                "<description>News details</description><link>https://example.com/p{0}</link></item>".format(i)
                for i in ids
            ) + "</channel></rss>"
        state=DeliveryState()
        old=config("https://example.com/old-feed")
        new=config("https://example.com/new-feed")
        first=run(old,state,fetch=lambda _:rss(1),
                  send=lambda *args:self.fail("first snapshot must not send"),
                  credentials={},now=NOW)
        self.assertEqual(1,first.subscriptions_initialized)
        self.assertEqual(0,first.sent)
        redirected=run(new,state,fetch=lambda _:rss(50,51),
                       send=lambda *args:self.fail("different archive must warm silently"),
                       credentials={},now=NOW)
        self.assertEqual(1,redirected.subscriptions_initialized)
        self.assertEqual(0,redirected.sent)
        calls=[]
        later=run(new,state,fetch=lambda _:rss(50,51,52),
                  send=lambda dest,event,*_:calls.append(event.external_id) or True,
                  credentials={},now=NOW)
        self.assertEqual(1,later.sent)
        self.assertEqual(["post-52"],calls)

    def test_l2dex_source_url_switch_resets_castle_baseline(self):
        from test_l2dex_adapter import page, castle_row, NOW
        world={"network":"L2Dex","name":"New-Interlude x25","chronicle":"Interlude"}
        def config(url):
            return parse_config({
                "version":1,
                "sources":[{"id":"dex","kind":"l2dex_castles","url":url,"world":world}],
                "destinations":[{"id":"clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}],
                "subscriptions":[{"destination_id":"clan","world":world}],
            })
        original=config("https://lineage2dex.com/en/rating/new-interlude.343")
        alternate=config("https://lineage2dex.com/en/rating/new-interlude.344")
        state=DeliveryState()
        run(original,state,fetch=lambda _:page(castle_row(1,"Gludio Castle","ClanA")),
            send=lambda *args:True,credentials={},now=NOW)
        result=run(alternate,state,fetch=lambda _:page(castle_row(1,"Gludio Castle","ClanB")),
                   send=lambda *args:self.fail("new URL is not a verified owner transfer"),
                   credentials={},now=NOW)
        self.assertEqual(0,result.sent)
        self.assertEqual([],list(result.errors))
        # Future changes on that URL are observable after its own baseline.
        calls=[]
        followup=run(alternate,state,fetch=lambda _:page(castle_row(1,"Gludio Castle","ClanC")),
                     send=lambda target,event,*_:calls.append(event.kind) or True,
                     credentials={},now=NOW)
        self.assertEqual(1,followup.sent)
        self.assertEqual(["castle_owner_change"],calls)

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
