"""Challenge-page and corrupted-feed regression tests for GitHub-only mode."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest

from community.adapters.feeds import (
    parse_rss, parse_telegram_public, parse_webpage,
)
from community.config import parse_config, SourceConfig
from community.models import World
from community.runner import _init_key, run
from community.source_health import health_key, parser_identity
from community.state import DeliveryState

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
WORLD=World("Scryde","x1000")
CHANNEL="https://t.me/s/scryde"


def message(post, body="Patch update", **attrs):
    attribute=" ".join(f'{k}="{v}"' for k,v in attrs.items())
    return (
        '<div class="tgme_widget_message" data-post="{}" {}>'
        '<div class="tgme_widget_message_text">{}</div>'
        '<a class="tgme_widget_message_date" href="https://evil.example.invalid/post">Date</a>'
        '</div>'
    ).format(post,attribute,body)


def source(kind="telegram_public"):
    return SourceConfig("public",kind,WORLD,
                        CHANNEL if kind=="telegram_public" else "https://example.com/news")


def config():
    return parse_config({
        "version":1,
        "sources":[{"id":"public","kind":"telegram_public","url":CHANNEL,
                    "world":{"network":"Scryde","name":"x1000"}}],
        "destinations":[{"id":"channel","kind":"telegram",
                         "address_env":"CHAT","token_env":"TOKEN"}],
        "subscriptions":[{"destination_id":"channel",
                          "world":{"network":"Scryde","name":"x1000"}}],
    })


class PublicSourceFailClosedTests(unittest.TestCase):
    def test_rss_rejects_valid_xml_that_is_not_feed(self):
        for text in ("<html><body>Cloudflare challenge</body></html>",
                     "<error><message>Access denied</message></error>",
                     "<feed><item>Not valid Atom</item></feed>"):
            with self.subTest(text=text),self.assertRaises(ValueError):
                parse_rss(text,source("rss"),NOW)

    def test_empty_rss_is_legitimate_unlike_challenge(self):
        self.assertEqual([],parse_rss("<rss><channel/></rss>",source("rss"),NOW))
        atom='<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        self.assertEqual([],parse_rss(atom,source("rss"),NOW))

    def test_telegram_challenge_and_login_pages_fail_closed(self):
        for text in ("", "<html><body>CAPTCHA</body></html>",
                     "<div class='tgme_channel_info'>Private channel</div>"):
            with self.subTest(text=text),self.assertRaises(ValueError):
                parse_telegram_public(text,source(),NOW)

    def test_telegram_does_not_accept_other_channel_or_untrusted_ids(self):
        for name in ("other/123", "scryde/0", "scryde/-1",
                     "scryde/000123", "scryde/1x"):
            with self.subTest(name=name),self.assertRaises(ValueError):
                parse_telegram_public(message(name),source(),NOW)

    def test_telegram_uses_canonical_official_link_not_forged_href(self):
        events=parse_telegram_public(message("scryde/42"),source(),NOW)
        self.assertEqual(1,len(events))
        self.assertEqual("scryde/42",events[0].external_id)
        self.assertEqual("https://t.me/scryde/42",events[0].source_url)
        self.assertNotIn("evil.example.invalid",events[0].source_url)

    def test_telegram_duplicate_ids_are_quarantined(self):
        with self.assertRaises(ValueError):
            parse_telegram_public(message("scryde/42")+message("scryde/42","Other text"),
                                  source(),NOW)
        events=parse_telegram_public(
            message("scryde/42")+message("scryde/42","Other text")
            +message("scryde/43","Fresh news"),
            source(),NOW
        )
        self.assertEqual(["scryde/43"],[event.external_id for event in events])

    def test_telegram_mixed_other_channel_is_not_copied_to_scryde(self):
        events=parse_telegram_public(
            message("other/100","Other community")
            +message("scryde/101","Scryde community"),
            source(),NOW
        )
        self.assertEqual(["scryde/101"],[event.external_id for event in events])

    def test_webpage_without_expected_selector_is_not_empty_success(self):
        with self.assertRaises(ValueError):
            parse_webpage("<html><body>Just a CAPTCHA</body></html>",
                          source("webpage"),NOW)
        self.assertEqual(1,len(parse_webpage(
            "<main><h1>News</h1><p>Very important update for a Lineage 2 world.</p></main>",
            source("webpage"),NOW
        )))

    def test_challenge_does_not_initialize_a_new_telegram_subscription(self):
        cfg=config()
        state=DeliveryState()
        fetched=[]
        def challenge(url):
            fetched.append(url)
            return "<html><body>CAPTCHA</body></html>"
        first=run(cfg,state,fetch=challenge,
                  send=lambda *_:self.fail("must not send"),credentials={},now=NOW)
        self.assertEqual(1,len(first.errors))
        self.assertEqual(0,first.subscriptions_initialized)
        warm=_init_key(cfg.sources[0],cfg.subscriptions[0])
        self.assertNotIn(warm,state.cursors)
        parser_marker=health_key(parser_identity(cfg.sources[0]))
        self.assertIn(parser_marker,state.cursors)
        paused=run(cfg,state,fetch=lambda *_:self.fail("must honor backoff"),
                   send=lambda *_:self.fail("must not send"),
                   credentials={},now=NOW+timedelta(minutes=5))
        self.assertEqual(1,paused.deferred_sources)
        healthy=run(cfg,state,fetch=lambda _:message("scryde/42"),
                    send=lambda *_:self.fail("first genuine page is baseline"),
                    credentials={},now=NOW+timedelta(minutes=20))
        self.assertEqual(1,healthy.subscriptions_initialized)
        self.assertEqual(0,healthy.sent)
        self.assertNotIn(parser_marker,state.cursors)
        self.assertIn(warm,state.cursors)
        delivered=[]
        later=run(cfg,state,fetch=lambda _:message("scryde/42")+message("scryde/43"),
                  send=lambda dest,event,*args:delivered.append(event.external_id) or True,
                  credentials={},now=NOW+timedelta(minutes=40))
        self.assertEqual(1,later.sent)
        self.assertEqual(["scryde/43"],delivered)

    def test_existing_telegram_history_survives_temporary_challenge(self):
        cfg=config()
        state=DeliveryState()
        run(cfg,state,fetch=lambda _:message("scryde/42"),
            send=lambda *_:self.fail("warm start only"),credentials={},now=NOW)
        old_key=dict(state.delivered)
        run(cfg,state,fetch=lambda _:"<html><body>challenge</body></html>",
            send=lambda *_:self.fail("source is unavailable"),credentials={},
            now=NOW+timedelta(minutes=1))
        self.assertEqual(old_key,state.delivered)
        delivered=[]
        run(cfg,state,
            fetch=lambda _:message("scryde/42")+message("scryde/43"),
            send=lambda dest,event,*args:delivered.append(event.external_id) or True,
            credentials={},now=NOW+timedelta(minutes=21))
        self.assertEqual(["scryde/43"],delivered)


if __name__=="__main__":
    unittest.main()
