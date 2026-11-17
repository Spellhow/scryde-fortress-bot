"""Offline Unicode/world keyword matching and subscription isolation tests."""
import unittest
from datetime import datetime, timezone

from community.models import Event, World, Provenance
from community.config import SourceConfig, parse_config
from community.relevance import filter_events, mentions

NOW = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
WORLD = World("Scryde", "x1000")
URL = "https://t.me/s/scryde"


def feed_event(identifier, body):
    return Event(
        WORLD, "scryde-news", identifier, "news", body[:60], body,
        URL, Provenance.OBSERVED, NOW,
    )


def source(include=(), exclude=()):
    return SourceConfig(
        "scryde-news", "telegram_public", WORLD, URL,
        include_keywords=tuple(include), exclude_keywords=tuple(exclude),
    )


class RelevanceTests(unittest.TestCase):
    def test_world_100_does_not_match_1000(self):
        self.assertTrue(mentions("Update for x1000 players", "x1000"))
        self.assertFalse(mentions("Update for x1000 players", "x100"))
        self.assertFalse(mentions("Update for x100 players", "x1000"))

    def test_punctuation_and_cyrillic_word_boundaries(self):
        self.assertTrue(mentions("Оновлення для X1000! Кланова війна", "x1000"))
        self.assertTrue(mentions("Клан BSOE: оголошення", "клан"))
        self.assertFalse(mentions("безклановий", "клан"))

    def test_include_keeps_only_selected_world(self):
        events = [feed_event("one", "Новини x100"),feed_event("two", "Новини x1000")]
        result = filter_events(events, source(include=("x1000",)))
        self.assertEqual(["two"], [e.external_id for e in result])

    def test_exclude_overrides_include(self):
        events = [
            feed_event("one", "x1000 обнова"),
            feed_event("two", "x1000 турнір, скасовано"),
        ]
        result = filter_events(events, source(include=("x1000",), exclude=("турнір",)))
        self.assertEqual(["one"],[e.external_id for e in result])

    def test_multi_keyword_is_any_of(self):
        events = [feed_event("one", "x1000"), feed_event("two", "High Five"),
                  feed_event("three", "x50")]
        result=filter_events(events, source(include=("x1000","High Five")))
        self.assertEqual(["one","two"],[e.external_id for e in result])

    def test_no_implicit_filter_for_preexisting_config(self):
        events=[feed_event("one","General servers announcement")]
        self.assertEqual(events, filter_events(events, source()))

    def test_url_cannot_accidentally_match_world(self):
        events=[Event(WORLD, "feed", "post1", "news", "General", "All worlds",
                      "https://example.com/x1000", Provenance.OBSERVED,NOW)]
        self.assertEqual([],filter_events(events,source(include=("x1000",))))

    def test_unicode_control_and_excessive_keywords_rejected(self):
        with self.assertRaises(ValueError):
            source(include=("x1000\nsecret",))
        with self.assertRaises(ValueError):
            source(include=tuple(str(i) for i in range(13)))

    def test_l2dex_castle_source_rejects_news_keyword_filters(self):
        with self.assertRaises(ValueError):
            SourceConfig("dex","l2dex_castles",World("L2Dex","New-Interlude x25"),
                         "https://lineage2dex.com/en/rating/new-interlude.343",
                         include_keywords=("ClanA",))

    def test_json_config_parses_keyword_lists(self):
        world={"network":"Scryde","name":"x1000"}
        config=parse_config({
            "version":1,
            "sources":[{
                "id":"official","kind":"telegram_public","world":world,
                "url":URL,"include_keywords":["x1000"],"exclude_keywords":["x50"]
            }],
            "destinations":[{"id":"clan","kind":"telegram","address_env":"CHAT","token_env":"TOKEN"}],
            "subscriptions":[{"destination_id":"clan","world":world}],
        })
        self.assertEqual(("x1000",), config.sources[0].include_keywords)
        self.assertEqual(("x50",), config.sources[0].exclude_keywords)


if __name__ == "__main__":
    unittest.main()
