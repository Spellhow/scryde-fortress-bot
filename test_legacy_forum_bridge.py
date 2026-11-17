"""Scoped Scryde public forum checkpoint migration: no network or real messages."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from community.config import parse_config
from community.legacy_forum_bridge import (
    prepare_public_forum_watermark, suppress_legacy_forum_post,
    forum_watermark_key,
)
from community.models import Event, Provenance
from community.runner import run
from community.state import DeliveryState
from scripts.prepare_legacy_forum_watermark import main as forum_cli
from test_scryde_forum_adapter import config as example_forum_config, html


NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
SENTINEL="PRIVATE-NEWS-CONTENT-MUST-NOT-LEAK"
WORLD={"network":"Scryde","name":"x1000"}


def historical():
    return {
        "forum_news":{
            "last_seen_id":200,
            "sent_ids":[197,199,200],
            "pending":[
                {"post_id":197,"source":"forum","status":"published","text":SENTINEL},
                {"post_id":198,"source":"telegram","status":"cancelled","text":SENTINEL},
                {"post_id":200,"source":"forum","status":"expired","text":SENTINEL},
            ],
        },
        "news":{"pending":[{"post_id":50,"status":"published","text":SENTINEL}],
                "last_seen_id":50,"sent_ids":[50]},
    }


def entry(source,number):
    return Event(
        source.world,source.id,f"forum-post:{number}",
        "news","Scryde x1000 update","Public text",
        source.url+"#post-"+str(number),Provenance.OBSERVED,NOW,
    )


class LegacyForumBridgeTests(unittest.TestCase):
    def test_checkpoint_is_anonymous_and_does_not_mutate_inputs(self):
        cfg=example_forum_config()
        old=historical()
        before=json.dumps(old,sort_keys=True)
        current=DeliveryState({"one-receipt":42},{"warm:old":"initialized"})
        merged=prepare_public_forum_watermark(
            old,cfg,"scryde-public-forum","alpha",current
        )
        self.assertEqual(before,json.dumps(old,sort_keys=True))
        self.assertEqual({"one-receipt":42},merged.delivered)
        self.assertEqual({"warm:old":"initialized"},current.cursors)
        key=forum_watermark_key(cfg.sources[0],"alpha")
        self.assertEqual("200",merged.cursors[key])
        text=json.dumps({"delivered":merged.delivered,"cursors":merged.cursors})
        self.assertNotIn(SENTINEL,text)
        self.assertNotIn("board.scryde.net",text)
        self.assertNotIn("CHAT_A",text)

    def test_old_forum_posts_suppressed_only_for_original_telegram_destination(self):
        cfg=example_forum_config()
        src=cfg.sources[0]
        state=prepare_public_forum_watermark(
            historical(),cfg,src.id,"alpha",DeliveryState()
        )
        for num in (10,199,200):
            self.assertTrue(suppress_legacy_forum_post(state,src,"alpha",entry(src,num)))
            self.assertFalse(suppress_legacy_forum_post(state,src,"beta",entry(src,num)))
        self.assertFalse(suppress_legacy_forum_post(state,src,"alpha",entry(src,201)))
        self.assertEqual({},state.delivered)

    def test_page_number_changes_do_not_invalidate_same_thread_marker(self):
        cfg_a=example_forum_config()
        cfg_b=example_forum_config(
            url="https://board.scryde.net/threads/obnovlenija.30694/page-17"
        )
        self.assertEqual(forum_watermark_key(cfg_a.sources[0],"alpha"),
                         forum_watermark_key(cfg_b.sources[0],"alpha"))
        current=prepare_public_forum_watermark(
            historical(),cfg_a,cfg_a.sources[0].id,"alpha",DeliveryState()
        )
        self.assertTrue(suppress_legacy_forum_post(
            current,cfg_b.sources[0],"alpha",entry(cfg_b.sources[0],199)
        ))

    def test_page_change_does_not_silently_warm_and_drop_new_posts(self):
        original=example_forum_config()
        next_page=example_forum_config(
            url="https://board.scryde.net/threads/obnovlenija.30694/page-17"
        )
        state=prepare_public_forum_watermark(
            historical(),original,"scryde-public-forum","alpha",DeliveryState()
        )
        initial=run(
            original,state,fetch=lambda _:html((199,"Scryde x1000 old post")),
            send=lambda *_:self.fail("initial warm must be silent"),
            credentials={},now=NOW,
        )
        self.assertEqual(2,initial.subscriptions_initialized)
        attempts=[]
        result=run(
            next_page,state,fetch=lambda _:html(
                (199,"Scryde x1000 old post"),
                (201,"Scryde x1000 latest post")
            ),
            send=lambda destination,event,*args:attempts.append(
                (destination.id,event.external_id)) or True,
            credentials={},now=NOW,
        )
        self.assertEqual(0,result.subscriptions_initialized)
        self.assertEqual(
            [("alpha","forum-post:201"),("beta","forum-post:201")],
            attempts
        )

    def test_wrong_source_kind_world_or_destination_rejected(self):
        for kwargs in (
            {"kind":"rss"},
            {"url":"https://evil.example.com/threads/obnovlenija.30694"},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                cfg=example_forum_config(**kwargs)
                prepare_public_forum_watermark(
                    historical(),cfg,"scryde-public-forum","alpha",DeliveryState()
                )
        with self.assertRaises(ValueError):
            prepare_public_forum_watermark(
                historical(),example_forum_config(),"scryde-public-forum",
                "beta",DeliveryState()
            )

    def test_active_unknown_or_future_legacy_history_rejected(self):
        for item in (
            {"post_id":100,"status":"pending"},
            {"post_id":100,"status":"approved"},
            {"post_id":100,"status":"other"},
            {"post_id":201,"status":"published"},
            {"post_id":False,"status":"published"},
        ):
            with self.subTest(item=item),self.assertRaises(ValueError):
                old=historical()
                old["forum_news"]["pending"]=[item]
                prepare_public_forum_watermark(
                    old,example_forum_config(),"scryde-public-forum",
                    "alpha",DeliveryState()
                )

    def test_existing_different_checkpoint_must_not_be_rewound(self):
        cfg=example_forum_config()
        current=prepare_public_forum_watermark(
            historical(),cfg,"scryde-public-forum","alpha",DeliveryState()
        )
        changed=historical()
        changed["forum_news"]["last_seen_id"]=201
        with self.assertRaises(ValueError):
            prepare_public_forum_watermark(
                changed,cfg,"scryde-public-forum","alpha",current
            )

    def test_malformed_and_unrelated_event_ids_not_suppressed(self):
        cfg=example_forum_config()
        src=cfg.sources[0]
        current=prepare_public_forum_watermark(
            historical(),cfg,"scryde-public-forum","alpha",DeliveryState()
        )
        for ext in ("forum-post:0","forum-post:-1","forum-post:0200",
                    "scryde/200","forum-post:"+"9"*9000):
            with self.subTest(len=len(ext)):
                altered=Event(src.world,src.id,ext,"news","title","body",
                              src.url,Provenance.OBSERVED,NOW)
                self.assertFalse(suppress_legacy_forum_post(
                    current,src,"alpha",altered
                ))

    def test_runner_preserves_old_forum_ids_without_recording_fake_delivery(self):
        cfg=example_forum_config()
        state=prepare_public_forum_watermark(
            historical(),cfg,"scryde-public-forum","alpha",DeliveryState()
        )
        initial=html((197,"Scryde x1000 original post"))
        run(cfg,state,fetch=lambda _:initial,send=lambda *_:True,
            credentials={},now=NOW)
        old_event=entry(cfg.sources[0],197)
        self.assertFalse(state.was_delivered("alpha",old_event.event_id))
        delivered=[]
        page=html((197,"Scryde x1000 original post"),
                  (199,"Scryde x1000 earlier update"),
                  (201,"Scryde x1000 fresh patch"))
        result=run(cfg,state,fetch=lambda _:page,
                   send=lambda destination,event,*args:delivered.append(
                       (destination.id,event.external_id)) or True,
                   credentials={},now=NOW)
        self.assertEqual(
            [("alpha","forum-post:201"),
             ("beta","forum-post:199"),
             ("beta","forum-post:201")],
            delivered
        )
        self.assertEqual(3,result.sent)
        again=run(cfg,state,fetch=lambda _:page,
                  send=lambda *_:self.fail("no duplicate"),
                  credentials={},now=NOW)
        self.assertEqual(0,again.sent)

    def test_manual_cli_dry_run_and_write_candidate_without_mutating_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original=root/"legacy.json"
            config_file=root/"community.json"
            current=root/"community_deliveries.json"
            candidate=root/"candidate.json"
            old=historical()
            original.write_text(json.dumps(old),encoding="utf8")
            cfg={
                "version":1,
                "sources":[{
                    "id":"scryde-public-forum","kind":"scryde_forum",
                    "url":"https://board.scryde.net/threads/obnovlenija.30694/page-18",
                    "world":WORLD,"include_keywords":["x1000"]
                }],
                "destinations":[{"id":"alpha","kind":"telegram",
                                 "address_env":"CHAT_A","token_env":"TOKEN"}],
                "subscriptions":[{"destination_id":"alpha","world":WORLD}]
            }
            config_file.write_text(json.dumps(cfg),encoding="utf8")
            args=[
                "--legacy",str(original),"--config",str(config_file),
                "--current",str(current),
                "--source-alias","scryde-public-forum",
                "--destination-alias","alpha"
            ]
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(0,forum_cli(args))
            report=json.loads(output.getvalue())
            self.assertFalse(report["output_written"])
            self.assertFalse(report["cutover_authorized"])
            self.assertFalse(candidate.exists())
            self.assertEqual(1,report["unmapped_legacy_telegram_items"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0,forum_cli(args+[
                    "--output",str(candidate),"--confirm"
                ]))
            result=json.loads(candidate.read_text())
            self.assertEqual(1,len(result["cursors"]))
            self.assertNotIn(SENTINEL,candidate.read_text())
            self.assertEqual(json.loads(original.read_text()),old)
            self.assertFalse(current.exists())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2,forum_cli(args+[
                    "--output",str(candidate),"--confirm"
                ]))

    def test_cli_invalid_metadata_fails_without_private_output(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            original=folder/"old.json"
            config_file=folder/"config.json"
            output=folder/"candidate.json"
            raw=historical()
            raw["news"]="SECRET-PLEASE-NEVER-PRINT"
            original.write_text(json.dumps(raw),encoding="utf8")
            config_file.write_text(json.dumps({
                "version":1,
                "sources":[{
                    "id":"scryde-public-forum","kind":"scryde_forum",
                    "url":"https://board.scryde.net/threads/obnovlenija.30694/page-18",
                    "world":WORLD,"include_keywords":["x1000"]
                }],
                "destinations":[{"id":"alpha","kind":"telegram",
                                 "address_env":"CHAT_A","token_env":"TOKEN"}],
                "subscriptions":[{"destination_id":"alpha","world":WORLD}]
            }),encoding="utf8")
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(2,forum_cli([
                    "--legacy",str(original),"--config",str(config_file),
                    "--current",str(folder/"none.json"),
                    "--source-alias","scryde-public-forum",
                    "--destination-alias","alpha",
                    "--output",str(output),"--confirm"
                ]))
            self.assertFalse(output.exists())
            self.assertNotIn("SECRET",errors.getvalue())


if __name__ == "__main__":
    unittest.main()
