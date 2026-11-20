"""Offline secret preflight and GitHub-only partial availability contracts."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from community.config import parse_config, credential_environment
from community.credential_preflight import check_credentials, active_destination_ids
from community.state import DeliveryState
from community.runner import run
from community_runner import main

SECRET="PRIVATE-TOKEN-NEVER-PRINT"
WORLD={"network":"L2Dex","name":"New-Interlude x25"}


def document():
    return {
        "version":1,
        "sources":[
            {"id":"live","kind":"rss","url":"https://example.com/rss",
             "world":WORLD},
            {"id":"disabled","kind":"rss","url":"https://example.com/disabled",
             "world":WORLD,"enabled":False},
        ],
        "destinations":[
            {"id":"tg","kind":"telegram","address_env":"TG_CHAT","token_env":"TG_TOKEN"},
            {"id":"discord","kind":"discord","address_env":"DISCORD_WEBHOOK"},
            {"id":"sleeping","kind":"telegram","address_env":"SLEEP_CHAT","token_env":"SLEEP_TOKEN"},
            {"id":"idle","kind":"telegram","address_env":"IDLE_CHAT","token_env":"IDLE_TOKEN"},
        ],
        "subscriptions":[
            {"destination_id":"tg","world":WORLD,"source_ids":["live"]},
            {"destination_id":"discord","world":WORLD,"source_ids":["live"]},
            {"destination_id":"sleeping","world":WORLD,"source_ids":["disabled"]},
        ],
    }


def credentials():
    return {
        "TG_CHAT":"-100123456789","TG_TOKEN":SECRET,
        "DISCORD_WEBHOOK":"https://discord.com/api/webhooks/123456/validSecret",
    }


class CredentialPreflightTests(unittest.TestCase):
    def setUp(self):
        self.config=parse_config(document())

    def test_only_active_subscribed_destinations_checked(self):
        self.assertEqual({"tg","discord"},active_destination_ids(self.config))
        count,issues=check_credentials(self.config,credentials())
        self.assertEqual(2,count)
        self.assertEqual((),issues)

    def test_missing_discord_does_not_invalidate_ready_telegram_secret(self):
        ready=dict(credentials())
        ready.pop("DISCORD_WEBHOOK")
        count,issues=check_credentials(self.config,ready)
        self.assertEqual(2,count)
        self.assertEqual((("DISCORD_WEBHOOK","missing"),),issues)
        self.assertNotIn(SECRET,str(issues))
        # The preflight informs CI of a degraded install, but the actual
        # runner retains per-target isolation: healthy Telegram still sends.
        rss='<rss><channel><item><guid>1</guid><title>Old</title><description>Old news</description><link>https://example.com/1</link></item></channel></rss>'
        newer=rss.replace("</channel>",'<item><guid>2</guid><title>New</title><description>New news</description><link>https://example.com/2</link></item></channel>')
        state=DeliveryState()
        from datetime import datetime, timezone
        now=datetime(2026,11,20,tzinfo=timezone.utc)
        run(self.config,state,fetch=lambda _:rss,
            send=lambda *_:self.fail("warm start is silent"),
            credentials=ready,now=now)
        attempts=[]
        result=run(self.config,state,fetch=lambda _:newer,
                   send=lambda dest,*args: attempts.append(dest.id) or dest.id=="tg",
                   credentials=ready,now=now)
        self.assertEqual(1,result.sent)
        self.assertEqual(1,len(result.errors))
        self.assertEqual(["tg","discord"],attempts)

    def test_malformed_webhook_and_whitespace_tokens_rejected(self):
        creds=credentials()
        creds["DISCORD_WEBHOOK"]="https://example.com/api/webhooks/123/SECRET"
        creds["TG_TOKEN"]="   "
        _,issues=check_credentials(self.config,creds)
        self.assertIn(("TG_TOKEN","missing"),issues)
        self.assertIn(("DISCORD_WEBHOOK","invalid Discord webhook URL"),issues)
        self.assertNotIn(creds["DISCORD_WEBHOOK"],str(issues))

    def test_bad_telegram_control_char_and_missing_token_reference(self):
        creds=credentials()
        creds["TG_CHAT"]="-100\nprivate"
        _,issues=check_credentials(self.config,creds)
        self.assertIn(("TG_CHAT","invalid Telegram address"),issues)
        data=document()
        data["destinations"][0]["token_env"]=""
        _,issues=check_credentials(parse_config(data),creds)
        self.assertIn(("token_env","missing Telegram token reference"),issues)

    def test_secret_json_map_supported_without_leaking_value(self):
        raw={"COMMUNITY_SECRETS_JSON":json.dumps(credentials())}
        conf=credential_environment(raw)
        self.assertEqual((),check_credentials(self.config,conf)[1])
        self.assertNotIn(SECRET,str(check_credentials(self.config,conf)))

    def test_disabled_only_sources_do_not_require_keys(self):
        data=document()
        data["sources"][0]["enabled"]=False
        self.assertEqual(set(),active_destination_ids(parse_config(data)))
        self.assertEqual((0,()),check_credentials(parse_config(data),{}))

    def test_manual_schedule_without_public_feed_requires_destination(self):
        data={
            "version":1,"sources":[],
            "scheduled_events":[{
                "id":"raid-event","world":WORLD,"title":"Reminder",
                "starts_at":"2026-11-30T12:00:00+00:00"
            }],
            "destinations":[{"id":"tg","kind":"telegram",
                             "address_env":"TG_CHAT","token_env":"TG_TOKEN"}],
            "subscriptions":[{"destination_id":"tg","world":WORLD,
                              "source_ids":["manual_schedule"],
                              "event_types":["event_reminder"]}],
        }
        conf=parse_config(data)
        self.assertEqual({"tg"},active_destination_ids(conf))
        self.assertEqual(2,len(check_credentials(conf,{})[1]))

    def test_cli_only_prints_missing_variable_names_and_no_file_written(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file=Path(directory)/"community.json"
            state_file=Path(directory)/"community_deliveries.json"
            config_file.write_text(json.dumps(document()),encoding="utf8")
            env={
                "COMMUNITY_CONFIG_FILE":str(config_file),
                "COMMUNITY_STATE_FILE":str(state_file),
                "TG_CHAT":"-100123456789",
                "TG_TOKEN":SECRET,
                "DISCORD_WEBHOOK":"",
                "COMMUNITY_SECRETS_JSON":"",
            }
            output=io.StringIO()
            with patch.dict("os.environ",env,clear=True),redirect_stdout(output):
                self.assertEqual(1,main(["--check-credentials"]))
            self.assertIn("active_destinations=2",output.getvalue())
            self.assertIn("DISCORD_WEBHOOK",output.getvalue())
            self.assertNotIn(SECRET,output.getvalue())
            self.assertNotIn("100123456789",output.getvalue())
            self.assertFalse(state_file.exists())

    def test_cli_json_secret_map_passes_and_never_calls_network(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file=Path(directory)/"community.json"
            config_file.write_text(json.dumps(document()),encoding="utf8")
            out=io.StringIO()
            with patch.dict("os.environ",{
                "COMMUNITY_CONFIG_FILE":str(config_file),
                "COMMUNITY_SECRETS_JSON":json.dumps(credentials()),
            },clear=True),redirect_stdout(out),patch(
                "community_runner.run",side_effect=AssertionError("must not fetch/send")
            ):
                self.assertEqual(0,main(["--check-credentials"]))
            self.assertIn("issues=0",out.getvalue())
            self.assertNotIn(SECRET,out.getvalue())

    def test_malformed_secret_map_error_is_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file=Path(directory)/"community.json"
            config_file.write_text(json.dumps(document()),encoding="utf8")
            out=io.StringIO()
            with patch.dict("os.environ",{
                "COMMUNITY_CONFIG_FILE":str(config_file),
                "COMMUNITY_SECRETS_JSON":"{secret:"+SECRET,
            },clear=True),redirect_stdout(out):
                self.assertEqual(2,main(["--check-credentials"]))
            self.assertNotIn(SECRET,out.getvalue())

    def test_workflow_checks_without_blocking_healthy_destinations(self):
        text=(Path(__file__).resolve().parent/".github/workflows/community-bot.yml").read_text()
        self.assertIn("python community_runner.py --check-credentials",text)
        self.assertIn("id: credentials_check",text)
        self.assertIn("continue-on-error: true",text)
        self.assertIn("steps.credentials_check.outcome == 'failure'",text)
        self.assertIn("COMMUNITY_SECRETS_JSON:",text)
        self.assertIn("vars.COMMUNITY_DRY_RUN != 'true'",text)


if __name__=="__main__":
    unittest.main()
