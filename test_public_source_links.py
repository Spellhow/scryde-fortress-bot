"""Public source links never publish credential-bearing URLs to channels.

All tests use pure parsing or mocked transport. No actual HTTP or secrets.
"""
from datetime import datetime, timezone
import unittest
from xml.sax.saxutils import escape

from community.adapters.feeds import (
    parse_json_api, parse_rss, parse_scryde_forum
)
from community.config import SourceConfig
from community.models import (
    Destination, Event, Provenance, World
)
from community.public_links import safe_public_link
from community.publishers import (
    _safe_discord_source_url, render_discord_embed,
    render_plain_event, send_event
)

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
WORLD=World("Scryde","x1000")


def event(url):
    return Event(
        WORLD,"feed","evt-1","news","Patch update","Safe body",url,
        Provenance.OBSERVED,NOW,
    )


def source(kind):
    return SourceConfig(
        "feed",kind,WORLD,
        "https://example.com/feed" if kind!="scryde_forum"
        else "https://board.scryde.net/threads/obnovlenija.30694/page-18",
        include_keywords=("x1000",) if kind=="scryde_forum" else (),
    )


class PublicLinkSafetyTests(unittest.TestCase):
    def test_public_https_and_tracking_query_are_preserved(self):
        for link in (
            "https://example.com/post",
            "https://example.com/post?utm_source=forum",
            "https://t.me/scryde/42",
            "https://board.scryde.net/threads/obnovlenija.30694/page-18#post-123",
        ):
            with self.subTest(link=link):
                self.assertEqual(link,safe_public_link(link))
                self.assertEqual(link,_safe_discord_source_url(link))

    def test_credentials_and_private_hosts_are_rejected(self):
        for link in (
            "http://example.com/post",
            "https://user:pass@example.com/post",
            "https://example.com/post?token=abcd",
            "https://example.com/post?access%5Ftoken=abcd",
            "https://example.com/post?api_key=abc",
            "https://example.com/post?session_id=123",
            "https://example.com/post?client_secret=abc",
            "https://example.com/#access_token=abc",
            "https://127.0.0.1/post",
            "https://192.168.1.1/post",
            "https://server.local/post",
            "https://internal.lan/post",
            "https://example.com:8080/post",
            "https://example.com/post#unsafe-fragment",
            "javascript:alert(1)",
            "https://example.com/space here",
            "https://example.com/"+("x"*700),
        ):
            with self.subTest(link=link):
                self.assertIsNone(safe_public_link(link))
                self.assertIsNone(_safe_discord_source_url(link))

    def test_malformed_urls_are_rejected_without_exception(self):
        for link in (None, "", "https://[not-valid-ip]/post", "https://example.com" + chr(10) + "Authorization: abc", 42):
            with self.subTest(link=link):
                self.assertIsNone(safe_public_link(link))

    def test_telegram_plain_message_drops_unsafe_source_url_only(self):
        bad=render_plain_event(event("https://example.com/post?token=TOPSECRET"),3900)
        self.assertIn("Patch update",bad)
        self.assertIn("Safe body",bad)
        self.assertNotIn("TOPSECRET",bad)
        self.assertNotIn("token=",bad)
        good=render_plain_event(event("https://example.com/post"),3900)
        self.assertIn("https://example.com/post",good)

    def test_discord_plain_and_embeds_use_identical_policy(self):
        e=event("https://example.com/post?secret=NOPE")
        text=render_plain_event(e,1900)
        self.assertNotIn("NOPE",text)
        self.assertNotIn("url",render_discord_embed(e))
        safe=event("https://board.scryde.net/threads/obnovlenija.30694/page-18#post-300")
        self.assertEqual(safe.source_url,render_discord_embed(safe)["url"])

    def test_both_send_transports_strip_untrusted_links(self):
        e=event("https://example.com/post?access_token=TOKEN-NOT-PUBLIC")
        telegram=Destination("t","telegram","CHAT","BOT_TOKEN")
        discord=Destination("d","discord","WEBHOOK")
        seen=[]
        def post(url,payload):
            seen.append(str(payload))
            if "api.telegram.org" in url:
                return 200,b'{"ok":true,"result":{"message_id":42}}'
            return 200,b'{"id":"123456"}'
        self.assertTrue(send_event(
            telegram,e,"en",
            {"CHAT":"test-chat","BOT_TOKEN":"test-token"},post
        ))
        self.assertTrue(send_event(
            discord,e,"en",
            {"WEBHOOK":"https://discord.com/api/webhooks/123/validtoken"},post
        ))
        self.assertEqual(2,len(seen))
        self.assertNotIn("TOKEN-NOT-PUBLIC","".join(seen))
        self.assertIn("Patch update","".join(seen))

    def test_rss_rejects_credential_post_links_but_keeps_public_ones(self):
        xml=(
            "<rss><channel>"
            "<item><guid>hidden</guid><title>Private link</title>"
            "<description>Do not forward</description>"
            "<link>https://example.com/post?token=secret</link></item>"
            "<item><guid>public</guid><title>Official news</title>"
            "<description>Public update</description>"
            "<link>https://example.com/post?utm_source=rss</link></item>"
            "</channel></rss>"
        )
        events=parse_rss(xml,source("rss"),NOW)
        self.assertEqual(["public"],[e.external_id for e in events])
        self.assertIn("utm_source",events[0].source_url)

    def test_json_api_rejects_unsafe_link_without_leaking_post(self):
        import json
        text=json.dumps({"events":[
            {"id":"unsafe","title":"Bad","body":"Content",
             "url":"https://example.com?auth=secret"},
            {"id":"safe","title":"Good","body":"Content",
             "url":"https://example.com/safe"},
        ]})
        items=parse_json_api(text,source("json_api"),NOW)
        self.assertEqual(["safe"],[e.external_id for e in items])

    def test_official_forum_post_anchor_is_still_available(self):
        from community.adapters.feeds import parse_scryde_forum
        html=(
            '<article class="message" data-content="post-305">'
            '<div class="bbWrapper">Scryde x1000 important update</div>'
            '</article>'
        )
        rows=parse_scryde_forum(html,source("scryde_forum"),NOW)
        self.assertEqual(1,len(rows))
        self.assertTrue(rows[0].source_url.endswith("#post-305"))
        self.assertEqual(rows[0].source_url,safe_public_link(rows[0].source_url))


if __name__=="__main__":
    unittest.main()
