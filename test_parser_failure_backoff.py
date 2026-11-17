"""Community GitHub-only parser health: isolated retry, no network or secrets."""
from datetime import datetime, timedelta, timezone
import json
import tempfile
from pathlib import Path
import unittest

from community.config import parse_config
from community.models import World
from community.runner import run
from community.source_health import SourceHealth, health_key, parser_identity
from community.state import DeliveryState

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
URL="https://example.com/mixed-feed"
RSS='<rss><channel><item><guid>a</guid><title>Patch</title><description>Update</description><link>https://example.com/a</link></item></channel></rss>'
RSS_NEXT=RSS.replace("</channel>",'<item><guid>b</guid><title>News</title><description>Update</description><link>https://example.com/b</link></item></channel>')


def config(*, two=False, selector=""):
    world={"network":"Scryde","name":"x1000"}
    sources=[{"id":"parser-one","kind":"rss","url":URL,
              "world":world,"selector":selector}]
    if two:
        sources.insert(0,{"id":"parser-json","kind":"json_api",
                          "url":URL,"world":world})
    return parse_config({
        "version":1,"sources":sources,
        "destinations":[{"id":"t","kind":"telegram",
                         "address_env":"CHANNEL","token_env":"TOKEN"}],
        "subscriptions":[{"destination_id":"t","world":world,
                          "source_ids":["parser-one"]}],
    })


class ParserBackoffTests(unittest.TestCase):
    def test_repeated_invalid_xml_stops_parsing_before_retry_window(self):
        cfg=config()
        state=DeliveryState()
        count=[]
        def broken(url):
            count.append(url)
            return '<rss><channel><item>'
        first=run(cfg,state,fetch=broken,send=lambda *_:self.fail("do not send"),
                  credentials={},now=NOW)
        self.assertEqual(1,len(first.errors))
        self.assertEqual(1,len(count))
        self.assertEqual(1,len(state.cursors))
        parse_key=health_key(parser_identity(cfg.sources[0]))
        self.assertIn(parse_key,state.cursors)
        self.assertNotIn(URL,json.dumps(state.cursors))
        skipped=run(cfg,state,fetch=lambda *_:self.fail("parser should be paused"),
                    send=lambda *_:self.fail("do not send"),credentials={},
                    now=NOW+timedelta(minutes=5))
        self.assertEqual(1,skipped.deferred_sources)
        self.assertEqual(0,len(skipped.errors))
        self.assertEqual(1,len(count))
        second=run(cfg,state,fetch=broken,send=lambda *_:self.fail("do not send"),
                   credentials={},now=NOW+timedelta(minutes=20))
        self.assertEqual(1,len(second.errors))
        self.assertEqual(2,len(count))
        self.assertFalse(SourceHealth(state).ready(
            parser_identity(cfg.sources[0]),NOW+timedelta(minutes=59)))
        self.assertTrue(SourceHealth(state).ready(
            parser_identity(cfg.sources[0]),NOW+timedelta(minutes=60)))

    def test_healthy_snapshot_recovers_parser_failure_and_warms_source(self):
        cfg=config()
        state=DeliveryState()
        parser_id=parser_identity(cfg.sources[0])
        run(cfg,state,fetch=lambda _: '<rss>broken',
            send=lambda *_:self.fail("do not send"),credentials={},now=NOW)
        resumed=run(cfg,state,fetch=lambda _:RSS,
                    send=lambda *_:self.fail("warm start is silent"),
                    credentials={},now=NOW+timedelta(minutes=20))
        self.assertEqual(0,len(resumed.errors))
        self.assertEqual(1,resumed.subscriptions_initialized)
        self.assertNotIn(health_key(parser_id),state.cursors)
        sent=[]
        later=run(cfg,state,fetch=lambda _:RSS_NEXT,
                  send=lambda dest,event,*args:sent.append(event.external_id) or True,
                  credentials={},now=NOW+timedelta(minutes=40))
        self.assertEqual(1,later.sent)
        self.assertEqual(["b"],sent)

    def test_shared_url_parser_failure_does_not_pause_healthy_sibling(self):
        cfg=config(two=True)
        state=DeliveryState()
        called=[]
        for invocation,minute in enumerate((0,5,20),start=1):
            result=run(cfg,state,fetch=lambda url:called.append(url) or RSS,
                       send=lambda *_:True,credentials={},
                       now=NOW+timedelta(minutes=minute))
            if minute==5:
                self.assertEqual(1,result.deferred_sources)
                self.assertEqual(0,len(result.errors))
            else:
                self.assertEqual(1,len(result.errors))
            # Healthy sibling continues fetching on *every* scheduled run.
            self.assertEqual(invocation,len(called))
        self.assertIn(health_key(parser_identity(cfg.sources[0])),state.cursors)
        self.assertNotIn(health_key(parser_identity(cfg.sources[1])),state.cursors)

    def test_http_failure_still_blocks_same_url_and_does_not_fail_parser(self):
        cfg=config(two=True)
        state=DeliveryState()
        calls=[]
        def failed(url):
            calls.append(url)
            raise RuntimeError("token-secret-do-not-print")
        result=run(cfg,state,fetch=failed,
                   send=lambda *_:True,credentials={},now=NOW)
        self.assertEqual(1,len(calls))
        self.assertEqual(1,len(result.errors))
        self.assertEqual(1,result.deferred_sources)
        self.assertIn(health_key(URL),state.cursors)
        self.assertNotIn(health_key(parser_identity(cfg.sources[0])),state.cursors)
        self.assertNotIn(health_key(parser_identity(cfg.sources[1])),state.cursors)
        self.assertNotIn("token-secret-do-not-print",str(result.errors))
        self.assertNotIn(URL,json.dumps(state.cursors))

    def test_parser_identity_changes_when_config_changes(self):
        cfg=config()
        source=cfg.sources[0]
        from dataclasses import replace
        self.assertNotEqual(parser_identity(source),
                            parser_identity(replace(source,selector="main")))
        self.assertNotEqual(parser_identity(source),
                            parser_identity(replace(source,url="https://other.example.com/rss")))
        self.assertNotEqual(parser_identity(source),
                            parser_identity(replace(source,include_keywords=("x1000",))))

    def test_dry_run_does_not_add_or_recover_backoff_state(self):
        cfg=config()
        state=DeliveryState()
        key=parser_identity(cfg.sources[0])
        SourceHealth(state).fail(key,NOW)
        before=dict(state.cursors)
        result=run(cfg,state,fetch=lambda _:RSS,
                   send=lambda *_:self.fail("no sending"),credentials={},
                   now=NOW+timedelta(minutes=1),dry_run=True)
        self.assertEqual(0,len(result.errors))
        self.assertEqual(before,state.cursors)


if __name__ == "__main__":
    unittest.main()
