"""No-network public BSOE Telegram migration checkpoint tests.

Historical posts suppressed for ONLY one chosen destination. No secret
addresses, API calls or edits to legacy site_state.json.
"""
import contextlib
import io
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import unittest

from community.config import parse_config
from community.legacy_telegram_bridge import (
    prepare_public_telegram_watermark, suppress_legacy_public_news, watermark_key,
)
from community.models import Event, Provenance
from community.runner import run
from community.state import DeliveryState
from scripts.prepare_legacy_telegram_watermark import main as bridge_main

NOW=datetime(2026,11,17,11,tzinfo=timezone.utc)
PRIVATE="DO-NOT-DISCLOSE-PRIVATE-NEWS-CONTENT"
PUBLIC="https://t.me/s/scryde"
WORLD={"network":"Scryde","name":"x1000"}


def config(*, source_url=PUBLIC, source_kind="telegram_public", world=None):
    return parse_config({
        "version":1,
        "sources":[{"id":"telegram-feed","kind":source_kind,
                    "world":world or WORLD,"url":source_url}],
        "destinations":[
            {"id":"alpha","kind":"telegram","address_env":"CHAT_A","token_env":"TG_TOKEN"},
            {"id":"beta","kind":"telegram","address_env":"CHAT_B","token_env":"TG_TOKEN"},
        ],
        "subscriptions":[
            {"destination_id":"alpha","world":world or WORLD,"source_ids":["telegram-feed"]},
            {"destination_id":"beta","world":world or WORLD,"source_ids":["telegram-feed"]},
        ],
    })


def legacy(*, last_seen=100, pending=None):
    return {
        "news":{
            "last_seen_id":last_seen,
            "sent_ids":[96,98,100],
            "pending":pending if pending is not None else [
                {"post_id":98,"status":"published","text":PRIVATE},
                {"post_id":99,"status":"cancelled","text":PRIVATE},
                {"post_id":100,"status":"expired","text":PRIVATE},
            ],
        },
        "forum_news":{
            "last_seen_id":500,
            "sent_ids":[499],
            "pending":[{"post_id":499,"status":"published","text":PRIVATE}],
        },
    }


def sample_event(source, external_id, kind="news"):
    return Event(
        world=source.world,source_id=source.id,external_id=external_id,
        kind=kind,title="Public news",body="Public data",
        source_url="https://t.me/scryde/"+external_id.rsplit("/",1)[-1],
        provenance=Provenance.OBSERVED,observed_at=NOW,
    )


def html(*post_ids):
    return "".join(
        '<div class="tgme_widget_message" data-post="scryde/{0}">'
        '<div class="tgme_widget_message_text">Public update {0}</div>'
        '<a class="tgme_widget_message_date" href="https://t.me/scryde/{0}">Source</a>'
        "</div>".format(n) for n in post_ids
    )


class LegacyBridgeTests(unittest.TestCase):
    def test_import_is_immutable_and_hashed(self):
        cfg=config()
        old=legacy()
        current=DeliveryState(delivered={"receipt":10},cursors={"warm:old":"initialized"})
        before=json.dumps(old,sort_keys=True)
        prepared=prepare_public_telegram_watermark(
            old,cfg,"telegram-feed","alpha",current
        )
        self.assertEqual(before,json.dumps(old,sort_keys=True))
        self.assertEqual({"receipt":10},prepared.delivered)
        self.assertEqual({"receipt":10},current.delivered)
        self.assertEqual({"warm:old":"initialized"},current.cursors)
        self.assertEqual(100,int(prepared.cursors[watermark_key(cfg.sources[0],"alpha")]))
        exported=json.dumps({"cursors":prepared.cursors,"delivered":prepared.delivered})
        self.assertNotIn(PRIVATE,exported)
        self.assertNotIn("scryde",exported)
        self.assertNotIn("CHAT_A",exported)
        self.assertNotIn("pending",exported)

    def test_source_scoped_and_destination_scoped_suppression(self):
        cfg=config()
        src=cfg.sources[0]
        state=prepare_public_telegram_watermark(
            legacy(),cfg,src.id,"alpha",DeliveryState()
        )
        for ident in ("scryde/50","scryde/98","scryde/100"):
            self.assertTrue(suppress_legacy_public_news(
                state,src,"alpha",sample_event(src,ident)
            ))
            self.assertFalse(suppress_legacy_public_news(
                state,src,"beta",sample_event(src,ident)
            ))
        self.assertFalse(suppress_legacy_public_news(
            state,src,"alpha",sample_event(src,"scryde/101")
        ))
        self.assertEqual({},state.delivered)

    def test_oversized_public_post_number_is_never_parsed_or_suppressed(self):
        cfg=config()
        src=cfg.sources[0]
        checkpoint=prepare_public_telegram_watermark(
            legacy(),cfg,src.id,"alpha",DeliveryState()
        )
        self.assertFalse(suppress_legacy_public_news(
            checkpoint,src,"alpha",sample_event(src,"scryde/"+"9"*9000)
        ))

    def test_invalid_id_and_wrong_event_kind_not_suppressed(self):
        cfg=config()
        src=cfg.sources[0]
        checkpoint=prepare_public_telegram_watermark(
            legacy(),cfg,src.id,"alpha",DeliveryState()
        )
        for ident in ("not-a-message","other/99","scryde/0099","scryde/0","scryde/-1"):
            with self.subTest(ident=ident):
                self.assertFalse(suppress_legacy_public_news(
                    checkpoint,src,"alpha",sample_event(src,ident)
                ))
        self.assertFalse(suppress_legacy_public_news(
            checkpoint,src,"alpha",sample_event(src,"scryde/100","announcement")
        ))

    def test_rejects_unsupported_sources_and_worlds(self):
        for kwargs in (
            {"source_url":"https://t.me/s/anotherchannel"},
            {"source_kind":"rss"},
            {"world":{"network":"Other","name":"x1000"}},
            {"world":{"network":"Scryde","name":"x100"}},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                cfg=config(**kwargs)
                prepare_public_telegram_watermark(
                    legacy(),cfg,"telegram-feed","alpha",DeliveryState()
                )

    def test_unknown_destination_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare_public_telegram_watermark(
                legacy(),config(),"telegram-feed","missing",DeliveryState()
            )

    def test_active_or_malformed_legacy_queue_is_blocked(self):
        for posts in (
            [{"post_id":100,"status":"pending"}],
            [{"post_id":100,"status":"approved"}],
            [{"post_id":100,"status":"unknown"}],
            [{"post_id":101,"status":"published"}],
            [{"post_id":100,"status":"published","text":PRIVATE}, PRIVATE],
        ):
            with self.subTest(posts=str(type(posts[-1]))),self.assertRaises(ValueError):
                prepare_public_telegram_watermark(
                    legacy(pending=posts),config(),"telegram-feed","alpha",
                    DeliveryState()
                )

    def test_cursor_mismatch_and_malformed_sent_ids_fail(self):
        cfg=config()
        invalid=legacy()
        invalid["news"]["sent_ids"]=[101]
        with self.assertRaises(ValueError):
            prepare_public_telegram_watermark(
                invalid,cfg,"telegram-feed","alpha",DeliveryState()
            )
        prepared=prepare_public_telegram_watermark(
            legacy(),cfg,"telegram-feed","alpha",DeliveryState()
        )
        with self.assertRaises(ValueError):
            prepare_public_telegram_watermark(
                legacy(last_seen=101),cfg,"telegram-feed","alpha",prepared
            )

    def test_runtime_no_marker_remains_unchanged(self):
        cfg=config()
        state=DeliveryState()
        seen=[]
        run(cfg,state,fetch=lambda _:html(99),send=lambda d,e,l,c: seen.append(d.id) or True,
            credentials={},now=NOW)
        self.assertEqual([],seen)
        run(cfg,state,fetch=lambda _:html(99,101),
            send=lambda d,e,l,c: seen.append((d.id,e.external_id)) or True,
            credentials={},now=NOW)
        self.assertEqual([("alpha","scryde/101"),("beta","scryde/101")],seen)

    def test_runtime_scopes_suppression_and_delivers_new_posts(self):
        cfg=config()
        state=prepare_public_telegram_watermark(
            legacy(),cfg,"telegram-feed","alpha",DeliveryState()
        )
        sent=[]
        run(cfg,state,fetch=lambda _:html(98),
            send=lambda d,e,l,c:sent.append((d.id,e.external_id)) or True,
            credentials={},now=NOW)
        self.assertEqual([],sent)
        result=run(cfg,state,fetch=lambda _:html(98,101),
            send=lambda d,e,l,c:sent.append((d.id,e.external_id)) or True,
            credentials={},now=NOW)
        self.assertEqual(
            [("alpha","scryde/101"),("beta","scryde/101")],
            sent
        )
        self.assertEqual(2,result.sent)
        self.assertFalse(state.was_delivered("alpha",sample_event(cfg.sources[0],"scryde/98").event_id))

    def test_replay_old_after_warmup_suppresses_only_target(self):
        cfg=config()
        state=prepare_public_telegram_watermark(
            legacy(),cfg,"telegram-feed","alpha",DeliveryState()
        )
        run(cfg,state,fetch=lambda _:html(95),
            send=lambda *_:True,credentials={},now=NOW)
        calls=[]
        run(cfg,state,fetch=lambda _:html(95,96,101),
            send=lambda d,e,l,c:calls.append((d.id,e.external_id)) or True,
            credentials={},now=NOW)
        self.assertEqual(
            [("alpha","scryde/101"),("beta","scryde/96"),("beta","scryde/101")],
            calls
        )

    def test_cli_default_no_write_and_opt_in_writes_only_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            old=root/"legacy.json"
            old.write_text(json.dumps(legacy()),encoding="utf8")
            cfg=root/"community.json"
            cfg.write_text(json.dumps({
                "version":1,
                "sources":[{"id":"telegram-feed","kind":"telegram_public",
                            "url":PUBLIC,"world":WORLD}],
                "destinations":[
                    {"id":"alpha","kind":"telegram","address_env":"CHAT_A","token_env":"TG_TOKEN"}
                ],
                "subscriptions":[{"destination_id":"alpha","world":WORLD}],
            }),encoding="utf8")
            current=root/"community_deliveries.json"
            output=root/"prepared.json"
            args=["--legacy",str(old),"--config",str(cfg),"--current",str(current),
                  "--source-alias","telegram-feed","--destination-alias","alpha"]
            stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(0,bridge_main(args))
            self.assertNotIn(PRIVATE,stdout.getvalue())
            self.assertFalse(output.exists())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2,bridge_main(args+["--output",str(output)]))
            self.assertFalse(output.exists())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0,bridge_main(args+["--output",str(output),"--confirm"]))
            self.assertTrue(output.exists())
            saved=json.loads(output.read_text())
            self.assertEqual(1,saved["schema_version"])
            self.assertEqual(1,len(saved["cursors"]))
            self.assertNotIn(PRIVATE,output.read_text())
            self.assertEqual(json.loads(old.read_text()),legacy())
            self.assertFalse(current.exists())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2,bridge_main(args+["--output",str(output),"--confirm"]))

    def test_invalid_forum_shape_fails_without_writing_state(self):
        with tempfile.TemporaryDirectory() as td:
            from community.config import parse_config
            cfg=config()
            current=DeliveryState()
            data=legacy()
            data["forum_news"]="private-secret-invalid"
            # The pure bridge maps only the public Telegram section; the CLI
            # additionally rejects malformed unhandled forum metadata.
            prepare_public_telegram_watermark(
                data,cfg,"telegram-feed","alpha",current
            )
            conf=Path(td)/"config.json"
            conf.write_text(json.dumps({
                "version":1,
                "sources":[{"id":"telegram-feed","kind":"telegram_public","url":PUBLIC,"world":WORLD}],
                "destinations":[{"id":"alpha","kind":"telegram","address_env":"CHAT_A","token_env":"TG_TOKEN"}],
                "subscriptions":[{"destination_id":"alpha","world":WORLD}],
            }),encoding="utf8")
            old=Path(td)/"legacy.json"
            old.write_text(json.dumps(data),encoding="utf8")
            output=Path(td)/"candidate.json"
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(2,bridge_main([
                    "--legacy",str(old),"--config",str(conf),
                    "--current",str(Path(td)/"missing.json"),
                    "--source-alias","telegram-feed","--destination-alias","alpha",
                    "--output",str(output),"--confirm",
                ]))
            self.assertFalse(output.exists())
            self.assertNotIn("private-secret-invalid",errors.getvalue())

    def test_cli_rejects_invalid_target_without_output_or_secret_leak(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            old=root/"old.json"
            old.write_text(json.dumps(legacy()),encoding="utf8")
            out=root/"new.json"
            log=io.StringIO()
            with contextlib.redirect_stderr(log):
                self.assertEqual(2,bridge_main([
                    "--legacy",str(old),"--config",str(root/"not-found.json"),
                    "--source-alias","test","--destination-alias","test",
                    "--output",str(out),"--confirm"
                ]))
            self.assertFalse(out.exists())
            self.assertNotIn(str(old),log.getvalue())
            self.assertNotIn(PRIVATE,log.getvalue())


if __name__=="__main__":
    unittest.main()
