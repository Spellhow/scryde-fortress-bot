"""Preserve previously warmed forum destinations across the URL-key upgrade.

No network, real Telegram, Gemini calls or tracked legacy state mutation.
"""
from dataclasses import replace
from datetime import datetime, timezone
import unittest

from community.adapters.feeds import parse_scryde_forum
from community.runner import _init_key, run
from community.state import DeliveryState
from test_scryde_forum_adapter import config, html

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)


class ForumWarmMarkerUpgradeTests(unittest.TestCase):
    def test_stable_key_is_identical_across_numbered_pages(self):
        a=config()
        b=config(url="https://board.scryde.net/threads/obnovlenija.30694/page-19")
        stable_a=_init_key(a.sources[0],a.subscriptions[0])
        stable_b=_init_key(b.sources[0],b.subscriptions[0])
        old_a=_init_key(a.sources[0],a.subscriptions[0],legacy_page_identity=True)
        old_b=_init_key(b.sources[0],b.subscriptions[0],legacy_page_identity=True)
        self.assertEqual(stable_a,stable_b)
        self.assertNotEqual(old_a,old_b)
        self.assertNotEqual(stable_a,old_a)

    def test_upgrade_does_not_drop_new_post_or_resend_old(self):
        cfg=config()
        source=cfg.sources[0]
        alpha=cfg.subscriptions[0]
        old_marker=_init_key(source,alpha,legacy_page_identity=True)
        stable_marker=_init_key(source,alpha)
        previous=parse_scryde_forum(html((100,"Scryde x1000 old")),source,NOW)[0]
        state=DeliveryState(cursors={old_marker:"initialized"})
        state.mark_delivered("alpha",previous.event_id,int(NOW.timestamp()))
        calls=[]
        summary=run(
            cfg,state,fetch=lambda _:html((100,"Scryde x1000 old"),
                                          (101,"Scryde x1000 new")),
            send=lambda dest,event,*args:calls.append((dest.id,event.external_id)) or True,
            credentials={},now=NOW,
        )
        self.assertEqual([("alpha","forum-post:101")],calls)
        self.assertEqual(1,summary.sent)
        self.assertEqual(1,summary.subscriptions_initialized)  # beta is new
        self.assertEqual("initialized",state.cursors[stable_marker])
        self.assertEqual("initialized",state.cursors[old_marker])

    def test_upgraded_marker_survives_page_number_change(self):
        cfg=config()
        source=cfg.sources[0]
        alpha=cfg.subscriptions[0]
        state=DeliveryState(cursors={
            _init_key(source,alpha,legacy_page_identity=True):"initialized",
        })
        # Existing post was already handled by the pre-upgrade bot.
        old=parse_scryde_forum(html((100,"Scryde x1000 old")),source,NOW)[0]
        state.mark_delivered("alpha",old.event_id,int(NOW.timestamp()))
        first=run(
            cfg,state,fetch=lambda _:html((100,"Scryde x1000 old")),
            send=lambda *_:self.fail("old post resent"),
            credentials={},now=NOW,
        )
        self.assertEqual(1,first.subscriptions_initialized)
        later=config(url="https://board.scryde.net/threads/obnovlenija.30694/page-19")
        calls=[]
        second=run(
            later,state,fetch=lambda _:html((102,"Scryde x1000 page change")),
            send=lambda dest,event,*args:calls.append((dest.id,event.external_id)) or True,
            credentials={},now=NOW,
        )
        self.assertEqual(0,second.subscriptions_initialized)
        self.assertEqual(
            [("alpha","forum-post:102"),("beta","forum-post:102")],
            calls
        )

    def test_dry_run_never_promotes_marker(self):
        cfg=config()
        old_marker=_init_key(cfg.sources[0],cfg.subscriptions[0],legacy_page_identity=True)
        stable_marker=_init_key(cfg.sources[0],cfg.subscriptions[0])
        state=DeliveryState(cursors={old_marker:"initialized"})
        run(cfg,state,fetch=lambda _:html((200,"Scryde x1000 update")),
            send=lambda *_:self.fail("dry-run must not send"),
            credentials={},now=NOW,dry_run=True)
        self.assertNotIn(stable_marker,state.cursors)

    def test_invalid_legacy_marker_is_not_trusted(self):
        cfg=config()
        old_marker=_init_key(cfg.sources[0],cfg.subscriptions[0],legacy_page_identity=True)
        stable_marker=_init_key(cfg.sources[0],cfg.subscriptions[0])
        state=DeliveryState(cursors={old_marker:"unverified"})
        result=run(
            cfg,state,fetch=lambda _:html((200,"Scryde x1000 new")),
            send=lambda *_:self.fail("untrusted marker must not publish"),
            credentials={},now=NOW
        )
        self.assertEqual(2,result.subscriptions_initialized)
        self.assertEqual("initialized",state.cursors[stable_marker])
        self.assertEqual("unverified",state.cursors[old_marker])

    def test_changed_subscription_filters_do_not_promote_old_marker(self):
        before=config()
        after=config(include=["x50"])
        original_marker=_init_key(before.sources[0],before.subscriptions[0],
                                  legacy_page_identity=True)
        stable_after=_init_key(after.sources[0],after.subscriptions[0])
        self.assertNotEqual(
            original_marker,
            _init_key(after.sources[0],after.subscriptions[0],legacy_page_identity=True)
        )
        state=DeliveryState(cursors={original_marker:"initialized"})
        run(after,state,fetch=lambda _:html((201,"Scryde x50 new")),
            send=lambda *_:self.fail("changed filters must warm silently"),
            credentials={},now=NOW)
        self.assertEqual("initialized",state.cursors[stable_after])


if __name__=="__main__":
    unittest.main()
