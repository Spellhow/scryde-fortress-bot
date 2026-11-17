"""Public Scryde forum post identity and multi-destination offline behavior."""
from datetime import datetime, timezone
import unittest

from community.adapters.feeds import parse_scryde_forum
from community.config import parse_config
from community.preview import preview_sources
from community.runner import run
from community.state import DeliveryState


NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
SOURCE="https://board.scryde.net/threads/obnovlenija.30694/page-18"
WORLD={"network":"Scryde","name":"x1000"}


def config(*, url=SOURCE, kind="scryde_forum", include=None):
    return parse_config({
        "version":1,
        "sources":[{"id":"scryde-public-forum","kind":kind,"url":url,
                    "world":WORLD,"include_keywords":include if include is not None else ["x1000"]}],
        "destinations":[
            {"id":"alpha","kind":"telegram","address_env":"CHAT_A","token_env":"TOKEN"},
            {"id":"beta","kind":"discord","address_env":"DISCORD_WEBHOOK"},
        ],
        "subscriptions":[
            {"destination_id":"alpha","world":WORLD,"source_ids":["scryde-public-forum"]},
            {"destination_id":"beta","world":WORLD,"source_ids":["scryde-public-forum"]},
        ],
    })


def html(*items):
    return "<html><body>" + "".join(
        '<article class="message" data-content="post-{}">'
        '<div class="bbWrapper"><p>{}</p></div></article>'.format(
            ident,text
        ) for ident,text in items
    )+"</body></html>"


class PublicScrydeForumAdapterTests(unittest.TestCase):
    def test_public_post_ids_and_links_stable_across_text_rewrites(self):
        cfg=config()
        src=cfg.sources[0]
        rows=parse_scryde_forum(html((200,"Scryde x1000: change A"),
                                     (201,"Scryde x1000: change B")),src,NOW)
        self.assertEqual(["forum-post:200","forum-post:201"],[e.external_id for e in rows])
        self.assertEqual(["news","news"],[e.kind for e in rows])
        self.assertEqual(
            SOURCE+"#post-200",rows[0].source_url
        )
        self.assertEqual("observed",rows[0].provenance.value)
        changed=parse_scryde_forum(html((200,"Scryde x1000: edited text")),src,NOW)
        self.assertEqual(rows[0].event_id,changed[0].event_id)
        self.assertNotEqual(rows[0].fingerprint,changed[0].fingerprint)

    def test_html_sanitization_and_bounded_source_text(self):
        cfg=config()
        page=(
            '<article class="message" data-content="post-5">'
            '<div class="bbWrapper"><script>secretCode()</script>'
            '<p>Server x1000 announcement</p><style>hidden</style>'
            + ("a"*5000) +
            '</div></article>'
        )
        result=parse_scryde_forum(page,cfg.sources[0],NOW)
        self.assertEqual(1,len(result))
        self.assertNotIn("secretCode",result[0].body)
        self.assertLessEqual(len(result[0].body),3200)
        self.assertLessEqual(len(result[0].title),100)

    def test_duplicates_and_missing_post_numbers_fail_closed(self):
        cfg=config()
        conflict=html((5,"Scryde x1000 A"),(5,"Scryde x1000 B"))
        with self.assertRaises(ValueError):
            parse_scryde_forum(conflict,cfg.sources[0],NOW)
        mixed=html((5,"Scryde x1000 A"),(5,"Scryde x1000 B"),(6,"Scryde x1000 C"))
        result=parse_scryde_forum(mixed,cfg.sources[0],NOW)
        self.assertEqual(["forum-post:6"],[e.external_id for e in result])
        with self.assertRaises(ValueError):
            parse_scryde_forum(html(("x","invalid identifier")),cfg.sources[0],NOW)

    def test_antibot_and_empty_html_not_treated_as_valid_snapshot(self):
        cfg=config()
        for document in ("", "<html>captcha challenge</html>",
                         '<article class="message"><div class="bbWrapper">No ID</div></article>'):
            with self.subTest(document=document),self.assertRaises(ValueError):
                parse_scryde_forum(document,cfg.sources[0],NOW)

    def test_config_only_official_public_updates_thread_and_keywords(self):
        for url in (
            "http://board.scryde.net/threads/obnovlenija.30694",
            "https://evil.example.com/threads/obnovlenija.30694",
            "https://board.scryde.net/threads/private.123",
            SOURCE+"?token=secret",
            "https://board.scryde.net/threads/obnovlenija.30694/latest",
            "https://board.scryde.net/threads/obnovlenija.30694/page-0",
        ):
            with self.subTest(url=url),self.assertRaises(ValueError):
                config(url=url)
        with self.assertRaises(ValueError):
            config(include=[])
        self.assertEqual("scryde_forum",config().sources[0].kind)

    def test_preview_keeps_keyword_scope_and_never_sends(self):
        cfg=config()
        data=html((300,"Scryde x1000 balance changes"),
                  (301,"Scryde x50 only"),
                  (302,"Changes only for x100"))
        report=preview_sources(cfg,fetch=lambda _:data,now=NOW)
        self.assertEqual(1,report["sources_previews"])
        self.assertEqual(1,report["results"][0]["event_count"])
        self.assertIn("x1000",report["results"][0]["samples"][0])

    def test_runner_silent_initialization_and_new_post_fanout(self):
        cfg=config()
        state=DeliveryState()
        fetched=[]
        calls=[]
        def fetch(url):
            fetched.append(url)
            return html((300,"Scryde x1000 latest news"))
        first=run(cfg,state,fetch=fetch,
                  send=lambda *args:calls.append(args) or True,credentials={},now=NOW)
        self.assertEqual(1,len(fetched))
        self.assertEqual(2,first.subscriptions_initialized)
        self.assertEqual([],calls)
        next_html=html((300,"Scryde x1000 latest news"),
                       (301,"Scryde x1000 later update"),
                       (302,"Scryde x50 unrelated"))
        second=run(cfg,state,fetch=lambda _:next_html,
                   send=lambda target,event,language,creds:calls.append((target.id,event.external_id)) or True,
                   credentials={},now=NOW)
        self.assertEqual(2,second.sent)
        self.assertEqual(
            [("alpha","forum-post:301"),("beta","forum-post:301")],
            calls
        )
        repeated=run(cfg,state,fetch=lambda _:next_html,
                     send=lambda *args:self.fail("duplicate event"),
                     credentials={},now=NOW)
        self.assertEqual(0,repeated.sent)

    def test_failed_destination_retries_independently(self):
        cfg=config()
        state=DeliveryState()
        run(cfg,state,fetch=lambda _:html((300,"Scryde x1000 initial")),
            send=lambda *_:True,credentials={},now=NOW)
        attempts=[]
        def sender(target,event,language,creds):
            attempts.append(target.id)
            return target.id=="alpha"
        news=html((301,"Scryde x1000 update"))
        first=run(cfg,state,fetch=lambda _:news,
                  send=sender,credentials={},now=NOW)
        self.assertEqual(1,first.sent)
        self.assertEqual(1,len(first.errors))
        attempts.clear()
        second=run(cfg,state,fetch=lambda _:news,
                   send=lambda target,*args:attempts.append(target.id) or True,
                   credentials={},now=NOW)
        self.assertEqual(["beta"],attempts)
        self.assertEqual(1,second.sent)


if __name__=="__main__":
    unittest.main()
