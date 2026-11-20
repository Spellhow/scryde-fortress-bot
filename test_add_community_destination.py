"""Multiple isolated GitHub-first destinations, no live sends or credentials."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from community.config import parse_config
from community.runner import run
from community.state import DeliveryState
from scripts.add_community_destination import add_destination, main

NOW=datetime(2026,11,19,12,tzinfo=timezone.utc)
RSS='<rss><channel><item><guid>one</guid><title>Old</title><description>Old content</description><link>https://example.com/one</link></item></channel></rss>'
NEXT=RSS.replace("</channel>",'<item><guid>two</guid><title>New</title><description>New content</description><link>https://example.com/two</link></item></channel>')


def starter(kind="rss"):
    source={
        "id":"news-feed","kind":kind,"url":"https://example.com/rss",
        "world":{"network":"Lineage","name":"Chronicle C4"}
    }
    if kind=="l2dex_castles":
        source.update(
            url="https://lineage2dex.com/en/rating/new-interlude.343",
            world={"network":"L2Dex","name":"New-Interlude x25"}
        )
    return {
        "version":1,
        "sources":[source],
        "destinations":[
            {"id":"original","kind":"telegram",
             "address_env":"TG_CHAT","token_env":"TG_TOKEN"},
        ],
        "subscriptions":[
            {"destination_id":"original","world":source["world"],
             "source_ids":["news-feed"],"event_types":["news"]}
        ] if kind=="rss" else [
            {"destination_id":"original","world":source["world"],
             "source_ids":["news-feed"],"event_types":["siege_registration"]}
        ],
        "scheduled_events":[],
    }


def add(data, **kw):
    args={
        "source_id":"news-feed","alias":"new-channel","kind":"discord",
        "address_env":"SECOND_DISCORD_WEBHOOK",
        "language":"en",
    }
    args.update(kw)
    return add_destination(data,**args)


class AddDestinationTests(unittest.TestCase):
    def test_valid_json_adds_second_channel_without_mutating_input(self):
        initial=starter()
        before=deepcopy(initial)
        result=add(initial)
        self.assertEqual(before,initial)
        cfg=parse_config(result)
        self.assertEqual(2,len(cfg.destinations))
        self.assertEqual(2,len(cfg.subscriptions))
        self.assertEqual(
            ("new-channel","news-feed","en"),
            (cfg.subscriptions[1].destination_id,
             next(iter(cfg.subscriptions[1].source_ids)),
             cfg.subscriptions[1].language)
        )
        self.assertEqual("SECOND_DISCORD_WEBHOOK",cfg.destinations["new-channel"].address_env)
        self.assertNotIn("https://discord.com/api/webhooks",json.dumps(result))

    def test_one_fetch_two_destinations_one_failed_retries_its_event_only(self):
        cfg=parse_config(add(starter()))
        state=DeliveryState()
        requests=[]
        initial=run(
            cfg,state,
            fetch=lambda url:requests.append(url) or RSS,
            send=lambda *_:self.fail("first snapshot must not send"),
            credentials={},now=NOW
        )
        self.assertEqual(2,initial.subscriptions_initialized)
        self.assertEqual(1,len(requests))
        self.assertEqual(0,initial.sent)
        calls=[]
        def send(dest,event,lang,creds):
            calls.append((dest.id,event.external_id,lang))
            return dest.id=="original"
        result=run(
            cfg,state,
            fetch=lambda url:requests.append(url) or NEXT,
            send=send,credentials={},now=NOW
        )
        self.assertEqual(1,result.sent)
        self.assertEqual(1,len(result.errors))
        self.assertEqual(2,len(requests)) # one fetch per run, not destination
        self.assertEqual([
            ("original","two","uk"),("new-channel","two","en")
        ],calls)
        calls.clear()
        result=run(
            cfg,state,fetch=lambda _:NEXT,
            send=lambda dest,event,lang,cred:calls.append((dest.id,event.external_id)) or True,
            credentials={},now=NOW
        )
        self.assertEqual(1,result.sent)
        self.assertEqual([("new-channel","two")],calls)
        repeated=run(
            cfg,state,fetch=lambda _:NEXT,
            send=lambda *_:self.fail("duplicate send"),
            credentials={},now=NOW
        )
        self.assertEqual(0,repeated.sent)

    def test_selected_type_limit_and_clan_filter(self):
        cfg=parse_config(add(starter(),event_types=("patch_note",)))
        self.assertEqual(
            frozenset({"patch_note"}),cfg.subscriptions[1].event_types
        )
        for event_types in (("siege_registration",),("unsupported",)):
            with self.subTest(event_types=event_types),self.assertRaises(ValueError):
                add(starter(),event_types=event_types)
        with self.assertRaises(ValueError):
            add(starter(),clans=("BSOE",))
        cfg=parse_config(add(starter("l2dex_castles"),
            event_types=("siege_registration",),clans=("BSOE",)))
        self.assertEqual(frozenset({"BSOE"}),cfg.subscriptions[1].clans)

    def test_disallows_duplicate_or_unknown_source_and_bad_secrets(self):
        for overrides in (
            {"alias":"ORIGINAL"},
            {"alias":"missing source","source_id":"no-such-source"},
            {"source_id":"no-such-source"},
            {"address_env":"https://discord.com/api/webhooks/123/SECRET"},
            {"kind":"telegram","token_env":""},
            {"kind":"discord","token_env":"BOT_TOKEN"},
            {"language":"English"},
        ):
            with self.subTest(overrides=overrides),self.assertRaises(ValueError):
                add(starter(),**overrides)

    def test_telegram_destination_uses_referenced_secret_names_only(self):
        cfg=parse_config(add(starter(),kind="telegram",
            address_env="TG_SECOND_CHAT",token_env="TG_OTHER_BOT"))
        dest=cfg.destinations["new-channel"]
        self.assertEqual("TG_SECOND_CHAT",dest.address_env)
        self.assertEqual("TG_OTHER_BOT",dest.token_env)

    def test_cli_dry_candidate_does_not_rewrite_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original=root/"community.json"
            output=root/"community.updated.json"
            original.write_text(json.dumps(starter()),encoding="utf8")
            args=[
                "--config",str(original),"--source-id","news-feed",
                "--kind","discord","--alias","new-channel",
                "--address-env","SECOND_WEBHOOK",
                "--language","en","--output",str(output)
            ]
            before=original.read_bytes()
            with redirect_stdout(io.StringIO()) as output_stream:
                self.assertEqual(0,main(args))
            self.assertIn("Candidate config created",output_stream.getvalue())
            self.assertEqual(before,original.read_bytes())
            new=parse_config(json.loads(output.read_text()))
            self.assertIn("new-channel",new.destinations)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(2,main(args)) # exclusive file refuses overwrite
            self.assertEqual(before,original.read_bytes())

    def test_cli_refuses_overwriting_input_and_invalid_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original=root/"community.json"
            original.write_text(json.dumps(starter()),encoding="utf8")
            before=original.read_bytes()
            args=[
                "--config",str(original),"--source-id","news-feed",
                "--kind","telegram","--alias","new-channel",
                "--address-env","TG_SECOND","--output",str(original),
            ]
            with redirect_stderr(io.StringIO()):
                self.assertEqual(2,main(args))
            self.assertEqual(before,original.read_bytes())

    def test_cli_rejects_untrusted_inputs_without_leaking_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original=root/"community.json"
            output=root/"candidate.json"
            original.write_text(json.dumps(starter()),encoding="utf8")
            args=[
                "--config",str(original),"--source-id","news-feed",
                "--kind","discord","--alias","another",
                "--address-env","https://discord.com/api/webhooks/SECRET",
                "--output",str(output),
            ]
            errors=io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(2,main(args))
            self.assertNotIn("SECRET",errors.getvalue())
            self.assertFalse(output.exists())

    def test_cli_default_telegram_token_env_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original=root/"community.json"
            output=root/"candidate.json"
            original.write_text(json.dumps(starter()),encoding="utf8")
            args=[
                "--config",str(original),"--source-id","news-feed",
                "--kind","telegram","--alias","second",
                "--address-env","TG_SECOND_CHAT","--output",str(output),
            ]
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0,main(args))
            data=json.loads(output.read_text())
            target=data["destinations"][-1]
            self.assertEqual("TG_TOKEN",target["token_env"])
            self.assertEqual("TG_SECOND_CHAT",target["address_env"])


class AddDestinationWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.yaml=(Path(__file__).resolve().parent/
                   ".github/workflows/add-community-destination.yml").read_text()

    def test_manual_only_confirmation_and_default_branch_scope(self):
        import re
        content=self.yaml
        self.assertIn("workflow_dispatch:",content)
        self.assertNotIn("\n  schedule:",content)
        self.assertIn("github.repository != 'Spellhow/scryde-fortress-bot'",content)
        self.assertIn("github.ref_name == github.event.repository.default_branch",content)
        self.assertIn("&& inputs.confirm",content)
        self.assertIn("default: false",content)
        input_block=content.split("    inputs:",1)[1].split("\npermissions:",1)[0]
        keys=re.findall(r"^      ([a-z_]+):$",input_block,re.M)
        self.assertEqual(9,len(keys))
        self.assertLessEqual(len(keys),10)
        self.assertIn("address_env",keys)
        self.assertIn("token_env",keys)

    def test_workflow_uses_validated_candidate_cli_not_raw_json(self):
        content=self.yaml
        self.assertIn("python scripts/add_community_destination.py",content)
        self.assertIn("--config community.json",content)
        self.assertIn("--output community.updated.json",content)
        self.assertIn("mv -- community.updated.json community.json",content)
        self.assertIn("git add -- community.json",content)
        self.assertNotIn("git add .",content)
        self.assertIn("group: scryde-state",content)
        self.assertIn("cancel-in-progress: false",content)
        self.assertNotIn("git add -- site_state.json",content)
        self.assertNotIn("COMMUNITY_SECRETS_JSON",content)
        self.assertNotIn("secrets.",content)

    def test_dispatch_fields_are_quoted_environment_variables(self):
        content=self.yaml
        for name,field in (
            ("NEW_SOURCE_ID","source_id"),
            ("NEW_DESTINATION_ALIAS","destination_alias"),
            ("NEW_DESTINATION_KIND","kind"),
            ("NEW_ADDRESS_ENV","address_env"),
            ("NEW_TOKEN_ENV","token_env"),
            ("NEW_LANGUAGE","language"),
            ("NEW_EVENT_TYPES","event_types"),
            ("NEW_CLANS","clans"),
        ):
            self.assertIn(name+": ${{ inputs."+field+" }}",content)
            self.assertIn('"$'+name+'"',content)
        self.assertNotIn("echo $",content)


if __name__=="__main__":
    unittest.main()
