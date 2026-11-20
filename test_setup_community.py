"""Offline clean-template configuration generator tests."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.setup_community import build_document, write_document
from community.config import parse_config


class SetupTests(unittest.TestCase):
    def args(self, **changed):
        result = {
            "network": "L2Dex", "world": "New-Interlude x25", "chronicle": "Interlude",
            "source_kind": "l2dex_castles",
            "source_url": "https://lineage2dex.com/en/rating/new-interlude.343",
            "destination_kind": "telegram",
        }
        result.update(changed)
        return result

    def test_l2dex_telegram_generates_valid_config(self):
        document = build_document(**self.args())
        parsed = parse_config(document)
        self.assertEqual(1, len(parsed.sources))
        self.assertTrue(parsed.sources[0].enabled)
        self.assertEqual("New-Interlude x25", parsed.sources[0].world.name)
        self.assertEqual(frozenset({"castle_owner_change", "siege_registration"}),
                         parsed.subscriptions[0].event_types)

    def test_no_private_credentials_in_document(self):
        document = build_document(**self.args())
        content = json.dumps(document)
        self.assertIn("TG_TOKEN", content)
        self.assertIn("TG_CHAT", content)
        self.assertNotIn("api.telegram.org/bot", content)
        self.assertNotIn("chat_id", content)

    def test_discord_destination_uses_env_reference(self):
        document = build_document(**self.args(destination_kind="discord"))
        target = parse_config(document).destinations["clan-channel"]
        self.assertEqual("discord", target.kind)
        self.assertEqual("DISCORD_WEBHOOK", target.address_env)
        self.assertEqual("", target.token_env)

    def test_public_telegram_news_source(self):
        document = build_document(**self.args(
            network="Scryde", world="x1000", source_kind="telegram_public",
            source_url="https://t.me/s/scryde",
        ))
        self.assertEqual("news", document["subscriptions"][0]["event_types"][0])
        self.assertEqual("Scryde", document["sources"][0]["world"]["network"])

    def test_bad_source_url_and_alias_refused(self):
        with self.assertRaises(ValueError):
            build_document(**self.args(source_url="http://127.0.0.1/private"))
        with self.assertRaises(ValueError):
            build_document(**self.args(destination_alias="../../path"))

    def test_source_url_with_api_token_is_refused(self):
        with self.assertRaises(ValueError):
            build_document(**self.args(
                source_kind="rss",
                source_url="https://example.com/rss?api_key=private-value",
            ))

    def test_public_telegram_defaults_to_its_world_gate(self):
        document=build_document(**self.args(
            network="Scryde",world="x1000",
            source_kind="telegram_public", source_url="https://t.me/s/scryde"))
        self.assertEqual(["x1000"],document["sources"][0]["include_keywords"])
        parse_config(document)

    def test_public_scryde_forum_defaults_to_world_keyword(self):
        document=build_document(**self.args(
            network="Scryde",world="x1000",source_kind="scryde_forum",
            source_url="https://board.scryde.net/threads/obnovlenija.30694/page-18",
        ))
        self.assertEqual(["x1000"],document["sources"][0]["include_keywords"])
        self.assertEqual("scryde_forum",parse_config(document).sources[0].kind)

    def test_setup_supports_override_keyword_and_rejects_l2dex_filters(self):
        document=build_document(**self.args(
            network="Scryde",world="x1000",
            source_kind="telegram_public",source_url="https://t.me/s/scryde",
            include_keywords="x1000, High Five"))
        self.assertEqual(["x1000","High Five"],document["sources"][0]["include_keywords"])
        with self.assertRaises(ValueError):
            build_document(**self.args(include_keywords="x1000"))

    def test_setup_workflow_choice_list_stays_in_sync_with_supported_sources(self):
        import re
        from community.config import SOURCE_KINDS
        workflow=(Path(__file__).resolve().parent/
                  ".github/workflows/setup-community.yml").read_text(encoding="utf8")
        section=workflow.split("      source_kind:",1)[1].split("      source_url:",1)[0]
        choices=set(re.findall(r"^          - ([a-z0-9_]+)$",section,re.M))
        self.assertEqual(SOURCE_KINDS,choices)
        self.assertIn("scryde_forum",choices)

    def test_news_sources_reject_clan_filter_instead_of_silent_empty_channel(self):
        cases=(
            ("rss","https://example.org/feed"),
            ("telegram_public","https://t.me/s/scryde"),
            ("json_api","https://example.org/data.json"),
            ("webpage","https://example.org/news"),
            ("scryde_forum",
             "https://board.scryde.net/threads/obnovlenija.30694/page-18"),
        )
        for kind,url in cases:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                build_document(**self.args(
                    network="Scryde",world="x1000",source_kind=kind,
                    source_url=url,clan="BSOE"
                ))

    def test_l2dex_owner_clan_filter_still_works(self):
        document=build_document(**self.args(clan="  BSOE  "))
        cfg=parse_config(document)
        self.assertEqual(frozenset({"BSOE"}),cfg.subscriptions[0].clans)
        with self.assertRaises(ValueError):
            build_document(**self.args(clan=None))

    def test_setup_cli_refuses_news_clan_and_does_not_create_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"community.json"
            argv=[
                sys.executable,str(Path(__file__).resolve().parent/"scripts/setup_community.py"),
                "--network","Scryde","--world","x1000",
                "--source-kind","scryde_forum",
                "--source-url","https://board.scryde.net/threads/obnovlenija.30694/page-18",
                "--clan","BSOE","--output",str(path),
            ]
            result=subprocess.run(argv,capture_output=True,text=True)
            self.assertEqual(2,result.returncode)
            self.assertIn("Setup refused",result.stderr)
            self.assertFalse(path.exists())

    def test_exclusive_file_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"community.json"
            document=build_document(**self.args())
            write_document(document,path)
            expected=path.read_text()
            with self.assertRaises(FileExistsError):
                write_document(document,path)
            self.assertEqual(expected,path.read_text())

    def test_cli_generator_and_existing_file_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"community.json"
            script=Path(__file__).resolve().parent/"scripts/setup_community.py"
            argv=[
                sys.executable,str(script),
                "--network","L2Dex", "--world","New-Interlude x25",
                "--source-kind","l2dex_castles",
                "--source-url","https://lineage2dex.com/en/rating/new-interlude.343",
                "--output",str(path),
            ]
            first=subprocess.run(argv,capture_output=True,text=True)
            self.assertEqual(0,first.returncode,first.stderr)
            self.assertEqual(1, len(parse_config(json.loads(path.read_text())) .sources))
            again=subprocess.run(argv,capture_output=True,text=True)
            self.assertNotEqual(0,again.returncode)
            self.assertIn("Setup refused",again.stderr)


if __name__ == "__main__":
    unittest.main()
