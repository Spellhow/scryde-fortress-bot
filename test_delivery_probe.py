"""Pure one-shot delivery probe contracts; does not contact Telegram/Discord."""
import contextlib
from datetime import datetime, timezone
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from community.config import parse_config
from community.delivery_probe import probe_destination
from community.models import Provenance
from scripts import test_delivery

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def config():
    world={"network":"L2Dex","name":"New-Interlude x25"}
    return parse_config({
        "version":1,
        "sources":[{"id":"dex","kind":"l2dex_castles",
                    "url":"https://lineage2dex.com/en/rating/new-interlude.343","world":world}],
        "destinations":[
            {"id":"tg","kind":"telegram","address_env":"TG_CHAT","token_env":"TG_TOKEN"},
            {"id":"discord","kind":"discord","address_env":"DISCORD_WEBHOOK"},
            {"id":"unsubscribed","kind":"telegram","address_env":"UNUSED_CHAT","token_env":"TG_TOKEN"},
        ],
        "subscriptions":[
            {"destination_id":"tg","world":world},
            {"destination_id":"discord","world":world},
        ],
    })


class DeliveryProbeTests(unittest.TestCase):
    def setUp(self):
        self.conf=config()
        self.env={
            "TG_CHAT":"-1000000000",
            "TG_TOKEN":"private-example",
            "DISCORD_WEBHOOK":"https://discord.com/api/webhooks/123456/token-test",
        }

    def test_one_explicit_manual_message(self):
        calls=[]
        def sender(dest,event,language,env):
            calls.append((dest.id, event, language))
            return True
        self.assertTrue(probe_destination(
            self.conf, "tg", self.env, sender=sender, at=NOW
        ))
        self.assertEqual(1,len(calls))
        alias,event,language=calls[0]
        self.assertEqual("tg",alias)
        self.assertEqual("manual_delivery_test", event.kind)
        self.assertEqual(Provenance.MANUAL, event.provenance)
        self.assertIn("No in-game siege",event.body)
        self.assertEqual("L2Dex",event.world.network)

    def test_unknown_destination_never_calls_sender(self):
        self.assertFalse(probe_destination(
            self.conf,"missing",self.env,
            sender=lambda *args:self.fail("never send"),at=NOW
        ))

    def test_unsubscribed_destination_never_calls_sender(self):
        self.assertFalse(probe_destination(
            self.conf,"unsubscribed",self.env,
            sender=lambda *args:self.fail("never send"),at=NOW
        ))

    def test_missing_token_prevents_send(self):
        self.assertFalse(probe_destination(
            self.conf,"tg",{"TG_CHAT":"-1"},
            sender=lambda *args:self.fail("never send"),at=NOW
        ))

    def test_missing_webhook_prevents_send(self):
        self.assertFalse(probe_destination(
            self.conf,"discord",{},
            sender=lambda *args:self.fail("never send"),at=NOW
        ))

    def test_false_response_is_never_success(self):
        self.assertFalse(probe_destination(
            self.conf,"discord",self.env,sender=lambda *args:False,at=NOW
        ))

    def test_invalid_time_rejected(self):
        with self.assertRaises(ValueError):
            probe_destination(
                self.conf,"tg",self.env,sender=lambda *args:True,
                at=datetime(2026,11,17)
            )

    @patch("scripts.test_delivery.load_config")
    @patch("scripts.test_delivery.credential_environment")
    @patch("scripts.test_delivery.probe_destination")
    def test_cli_refuses_without_confirmation(self, probe, creds, loaded):
        with patch.dict(os.environ,{
            "DELIVERY_TEST_CONFIRM":"no",
            "DELIVERY_TEST_DESTINATION":"tg",
        }),contextlib.redirect_stdout(io.StringIO()) as output:
            result=test_delivery.main()
        self.assertEqual(2,result)
        self.assertIn("confirmation required",output.getvalue())
        probe.assert_not_called()
        creds.assert_not_called()
        loaded.assert_not_called()

    @patch("scripts.test_delivery.load_config")
    @patch("scripts.test_delivery.credential_environment")
    @patch("scripts.test_delivery.probe_destination",return_value=True)
    def test_cli_confirmed_message_sanitized(self, probe, creds, loaded):
        loaded.return_value=self.conf
        creds.return_value=self.env
        with patch.dict(os.environ,{
            "DELIVERY_TEST_CONFIRM":"yes",
            "DELIVERY_TEST_DESTINATION":"tg",
        }),contextlib.redirect_stdout(io.StringIO()) as output:
            result=test_delivery.main()
        self.assertEqual(0,result)
        self.assertIn("Delivery confirmed",output.getvalue())
        self.assertNotIn(self.env["TG_TOKEN"],output.getvalue())
        self.assertNotIn(self.env["TG_CHAT"],output.getvalue())
        probe.assert_called_once()

    def test_original_repo_workflow_gate(self):
        from pathlib import Path
        path=Path(__file__).resolve().parent/".github/workflows/test-community-delivery.yml"
        text=path.read_text(encoding="utf8")
        self.assertIn("github.repository != 'Spellhow/scryde-fortress-bot'",text)
        self.assertIn("vars.COMMUNITY_MODE == 'true'",text)
        self.assertIn("inputs.confirm_send == true",text)
        self.assertIn("permissions:\n  contents: read",text)
        self.assertNotIn("schedule:",text)
        self.assertNotIn("persist_state",text)


if __name__ == "__main__":
    unittest.main()
