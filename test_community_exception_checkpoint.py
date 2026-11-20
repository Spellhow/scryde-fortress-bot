"""Offline checkpoint recovery when Community Bot fails after acknowledged sends."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from community.runner import run as actual_run
from community.state import DeliveryState
from community_runner import main

NOW=datetime(2026,11,20,12,tzinfo=timezone.utc)
PRIVATE="SECRET-IN-EXCEPTION-NOT-PUBLIC"

OLD=(
    '<rss><channel><item><guid>post-1</guid><title>Old news</title>'
    '<description>Old text</description><link>https://example.org/1</link>'
    '</item></channel></rss>'
)
NEXT=OLD.replace(
    '</channel>',
    '<item><guid>post-2</guid><title>New news</title>'
    '<description>New text</description><link>https://example.org/2</link>'
    '</item></channel>'
)


def setup(root):
    cfg=root/"community.json"
    state=root/"community_deliveries.json"
    world={"network":"Lineage","name":"Interlude"}
    cfg.write_text(json.dumps({
        "version":1,
        "sources":[{"id":"feed","kind":"rss","url":"https://example.org/rss",
                    "world":world}],
        "destinations":[
            {"id":"alpha","kind":"telegram","address_env":"CHAT_A","token_env":"TOKEN_A"},
            {"id":"beta","kind":"discord","address_env":"WEBHOOK_B"},
        ],
        "subscriptions":[
            {"destination_id":"alpha","world":world,"source_ids":["feed"]},
            {"destination_id":"beta","world":world,"source_ids":["feed"]},
        ],
    }),encoding="utf8")
    return cfg,state


class RunnerExceptionCheckpointTests(unittest.TestCase):
    def invoke(self, cfg, state, action, *, dry_run=False, env_error=False):
        env={
            "COMMUNITY_CONFIG_FILE":str(cfg),
            "COMMUNITY_STATE_FILE":str(state),
            "COMMUNITY_DRY_RUN":"true" if dry_run else "false",
        }
        stdout=io.StringIO()
        creds=lambda: {} if not env_error else (_ for _ in ()).throw(
            ValueError(PRIVATE)
        )
        with patch.dict("os.environ",env,clear=True), \
             patch("community_runner.credential_environment",side_effect=creds), \
             patch("community_runner.run",side_effect=action), \
             redirect_stdout(stdout):
            status=main([])
        return status,stdout.getvalue()

    def warm(self,cfg,state):
        from community.config import load_config
        loaded=DeliveryState()
        outcome=actual_run(load_config(cfg),loaded,fetch=lambda _:OLD,
                           send=lambda *_:self.fail("warm must be silent"),
                           credentials={},now=NOW)
        self.assertEqual(2,outcome.subscriptions_initialized)
        self.assertTrue(loaded.save(state))

    def test_two_accepted_messages_checkpointed_even_when_later_step_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg,state=setup(Path(directory))
            self.warm(cfg,state)
            attempted=[]
            def execute(c,record,**kwargs):
                return actual_run(
                    c,record,fetch=lambda _:NEXT,
                    send=lambda dest,event,*args:attempted.append(
                        (dest.id,event.external_id)
                    ) or True,
                    credentials={},now=NOW,
                )
            with patch("community.runner.due_reminders",
                       side_effect=RuntimeError(PRIVATE)):
                code,out=self.invoke(cfg,state,execute)
            self.assertEqual(1,code)
            self.assertIn("RuntimeError",out)
            self.assertNotIn(PRIVATE,out)
            self.assertEqual(
                [("alpha","post-2"),("beta","post-2")],attempted
            )
            from community.config import load_config
            from community.adapters.feeds import parse_rss
            events=parse_rss(NEXT,load_config(cfg).sources[0],NOW)
            news=next(item for item in events if item.external_id=="post-2")
            saved=DeliveryState.load(state)
            self.assertTrue(saved.was_delivered("alpha",news.event_id))
            self.assertTrue(saved.was_delivered("beta",news.event_id))
            # Restart should never resend already acknowledged messages.
            attempts=[]
            def restart(c,record,**kwargs):
                return actual_run(c,record,fetch=lambda _:NEXT,
                                  send=lambda dest,event,*a:attempts.append(dest.id) or True,
                                  credentials={},now=NOW)
            code,out=self.invoke(cfg,state,restart)
            self.assertEqual(0,code)
            self.assertEqual([],attempts)
            self.assertIn("sent=0",out)
            self.assertIn("state_changed=no",out)

    def test_unsuccessful_destination_is_not_falsely_acknowledged_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg,state=setup(Path(directory))
            self.warm(cfg,state)
            attempts=[]
            def deliver(c,record,**kwargs):
                return actual_run(c,record,fetch=lambda _:NEXT,
                    send=lambda dest,*a:attempts.append(dest.id) or dest.id=="alpha",
                    credentials={},now=NOW)
            with patch("community.runner.due_reminders",
                       side_effect=RuntimeError(PRIVATE)):
                rc,_=self.invoke(cfg,state,deliver)
            self.assertEqual(1,rc)
            self.assertEqual(["alpha","beta"],attempts)
            replay=[]
            def retry(c,record,**kwargs):
                return actual_run(c,record,fetch=lambda _:NEXT,
                    send=lambda dest,*a:replay.append(dest.id) or True,
                    credentials={},now=NOW)
            code,out=self.invoke(cfg,state,retry)
            self.assertEqual(0,code)
            self.assertEqual(["beta"],replay)
            self.assertIn("sent=1",out)

    def test_dry_run_error_never_writes_partial_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg,state=setup(Path(directory))
            def mutate_then_fail(_config,record,**kwargs):
                record.mark_delivered("alpha","hypothetical",123)
                raise RuntimeError(PRIVATE)
            code,out=self.invoke(cfg,state,mutate_then_fail,dry_run=True)
            self.assertEqual(1,code)
            self.assertFalse(state.exists())
            self.assertNotIn(PRIVATE,out)

    def test_credential_failure_never_creates_public_state(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg,state=setup(Path(directory))
            code,out=self.invoke(cfg,state,
                lambda *_a,**_kw:self.fail("run must not start"),
                env_error=True)
            self.assertEqual(1,code)
            self.assertFalse(state.exists())
            self.assertNotIn(PRIVATE,out)

    def test_corrupt_previous_state_not_overwritten_on_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg,state=setup(Path(directory))
            state.write_text("invalid current state",encoding="utf8")
            before=state.read_bytes()
            code,out=self.invoke(cfg,state,
                lambda *_a,**_kw:self.fail("run must not start"))
            self.assertEqual(1,code)
            self.assertEqual(before,state.read_bytes())
            self.assertNotIn("invalid current state",out)

    def test_failed_local_checkpoint_remains_reported_not_silenced(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg,state=setup(Path(directory))
            self.warm(cfg,state)
            previous=state.read_bytes()
            def mutate(_config,record,**kw):
                record.mark_delivered("alpha","post-999",123)
                raise RuntimeError(PRIVATE)
            with patch("community.state.os.replace",
                       side_effect=OSError(PRIVATE)):
                code,out=self.invoke(cfg,state,mutate)
            self.assertEqual(1,code)
            self.assertIn("OSError",out)
            self.assertNotIn(PRIVATE,out)
            self.assertEqual(previous,state.read_bytes())
            self.assertEqual(["community.json","community_deliveries.json"],
                             sorted(p.name for p in Path(directory).iterdir()))


if __name__=="__main__":
    unittest.main()
