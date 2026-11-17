"""Offline public source previews and per-host request ceilings."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from community.config import parse_config
from community.preview import preview_sources
from community.source_limits import (
    FetchBudget, FetchBudgetExceeded, FetchUnavailable,
)

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
WORLD={"network":"Scryde","name":"x1000"}


def make_config(*sources):
    return parse_config({"version":1,"sources":list(sources),"destinations":[],"subscriptions":[]})


def rss(source_id, url, include=()):
    return {"id":source_id,"kind":"rss","world":WORLD,"url":url,
            "include_keywords":list(include),"enabled":True}


class FetchBudgetTests(unittest.TestCase):
    def test_reuses_identical_url(self):
        budget=FetchBudget()
        calls=[]
        for _ in range(3):
            result=budget.read("https://example.com/one",lambda u:calls.append(u) or "content")
            self.assertEqual("content",result)
        self.assertEqual(["https://example.com/one"],calls)
        self.assertEqual(1,budget.domain_calls["example.com"])

    def test_one_domain_max_six_urls(self):
        budget=FetchBudget()
        seen=[]
        for i in range(6):
            budget.read("https://example.com/"+str(i),lambda u:seen.append(u) or "ok")
        with self.assertRaises(FetchBudgetExceeded):
            budget.read("https://example.com/extra",lambda u:self.fail("too many requests"))
        self.assertEqual(6,len(seen))

    def test_domains_are_independent(self):
        budget=FetchBudget(limit=1)
        calls=[]
        for host in ("one.example.com","two.example.com"):
            budget.read("https://"+host+"/a",lambda u:calls.append(u) or "ok")
        self.assertEqual(2,len(calls))

    def test_failed_public_fetch_is_cached_without_leaking_error(self):
        budget=FetchBudget()
        count=[]
        def fail(url):
            count.append(url)
            raise RuntimeError("token-do-not-log")
        for _ in range(2):
            with self.assertRaises(FetchUnavailable) as ctx:
                budget.read("https://example.com/feed",fail)
            self.assertNotIn("token-do-not-log",str(ctx.exception))
        self.assertEqual(1,len(count))

    def test_rejects_large_or_invalid_host_budget(self):
        for limit in (0, 7, "6"):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                FetchBudget(limit=limit)


class PreviewTests(unittest.TestCase):
    def test_rss_preview_respects_world_keywords_and_hides_body(self):
        config=make_config(rss("feed","https://example.com/rss",include=["x1000"]))
        payload=(
            "<rss><channel>"
            "<item><guid>1</guid><title>x100 announcement</title><description>secret body not for preview</description></item>"
            "<item><guid>2</guid><title>x1000 schedule</title><description>Details and instructions</description></item>"
            "</channel></rss>"
        )
        result=preview_sources(config,fetch=lambda _:payload,now=NOW)
        self.assertEqual(1,result["sources_previews"])
        self.assertEqual(1,result["results"][0]["event_count"])
        self.assertEqual(["x1000 schedule"],result["results"][0]["samples"])
        self.assertNotIn("Details and instructions",str(result))

    def test_same_url_two_worlds_reuses_one_fetch(self):
        sources=[
            rss("world100","https://example.com/shared"),
            {"id":"world1000","kind":"rss","world":{"network":"Scryde","name":"x1000-new"},
             "url":"https://example.com/shared","enabled":True},
        ]
        config=make_config(*sources)
        calls=[]
        payload="<rss><channel><item><guid>1</guid><title>Patch</title><description>General update</description></item></channel></rss>"
        result=preview_sources(config,fetch=lambda u:calls.append(u) or payload,now=NOW)
        self.assertEqual(2,result["sources_previews"])
        self.assertEqual(1,len(calls))

    def test_invalid_selected_alias_is_rejected(self):
        config=make_config(rss("feed","https://example.com/feed"))
        with self.assertRaises(ValueError):
            preview_sources(config,selected="wrong",fetch=lambda _:self.fail("never fetch"))

    def test_only_first_five_enabled_sources_are_previewed(self):
        config=make_config(*[rss("src"+str(i),"https://example.com/"+str(i)) for i in range(8)])
        result=preview_sources(config,fetch=lambda _:"<rss><channel/></rss>",now=NOW)
        self.assertEqual(8,result["sources_available"])
        self.assertEqual(5,result["sources_previews"])
        self.assertEqual(3,result["sources_skipped"])

    def test_l2dex_preview_shows_castle_without_claiming_live_event(self):
        from test_l2dex_adapter import page, castle_row
        world={"network":"L2Dex","name":"New-Interlude x25","chronicle":"Interlude"}
        config=make_config({
            "id":"l2dex","kind":"l2dex_castles",
            "world":world,"url":"https://lineage2dex.com/en/rating/new-interlude.343",
        })
        report=preview_sources(config,fetch=lambda _:page(castle_row(1,"Gludio Castle","ClanA")),now=NOW)
        self.assertEqual(["Gludio Castle: ClanA"],report["results"][0]["samples"])
        self.assertEqual(1,report["results"][0]["event_count"])
        self.assertNotIn("siege started",str(report).lower())

    def test_bad_html_is_safe_error_only(self):
        config=make_config(rss("feed","https://example.com/feed"))
        def bad(url):
            raise RuntimeError("Bearer secret-token must not print")
        report=preview_sources(config,fetch=bad,now=NOW)
        self.assertIn("error",report["results"][0])
        self.assertNotIn("Bearer",str(report))

    def test_preview_workflow_cannot_send_messages(self):
        path=Path(__file__).resolve().parent/".github/workflows/preview-community.yml"
        text=path.read_text()
        self.assertIn("vars.COMMUNITY_MODE == 'true'",text)
        self.assertIn("github.repository != 'Spellhow/scryde-fortress-bot'",text)
        self.assertIn("contents: read",text)
        self.assertNotIn("schedule:",text)
        self.assertNotIn("TG_TOKEN:",text)
        self.assertNotIn("DISCORD_WEBHOOK:",text)
        self.assertNotIn("persist_state",text)


if __name__ == "__main__":
    unittest.main()
