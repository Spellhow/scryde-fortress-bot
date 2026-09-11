import json
import unittest
from unittest.mock import patch

import requests

import wiki_patch_notes as wiki


class FakeResponse:
    def __init__(self, text, status_code=200, url=wiki.WIKI_URL):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("{} error".format(self.status_code))


def valid_wiki_html(title="Update 11.09.26"):
    payload = {
        "props": {
            "pageProps": {
                "preloadedArticle": {
                    "id": 77,
                    "title": title,
                    "content": "<p>Line one<br>Line two</p>",
                    "updated_at": 123456,
                    "created_at": 123000,
                }
            }
        }
    }
    return '<html><script id="__NEXT_DATA__" type="application/json">{}</script></html>'.format(
        json.dumps(payload)
    )


class WikiPatchNotesTests(unittest.TestCase):
    def test_parse_wiki_patch_note(self):
        article = wiki._parse_wiki_patch_note(valid_wiki_html(), wiki.WIKI_URL)
        self.assertEqual(article["id"], 123456)
        self.assertEqual(article["article_id"], 77)
        self.assertEqual(article["title"], "Update 11.09.26")
        self.assertIn("Line one", article["text"])
        self.assertIn("Line two", article["text"])
        self.assertEqual(article["url"], wiki.WIKI_URL)

    def test_variti_challenge_uses_browser_fallback(self):
        challenge = "<html><head><title>..</title></head><body><noscript>javascript disabled</noscript></body></html>"
        with patch.object(wiki.requests, "get", return_value=FakeResponse(challenge)):
            with patch.object(
                wiki,
                "_fetch_wiki_html_browser",
                return_value=(valid_wiki_html("Browser update"), wiki.WIKI_URL),
            ) as browser_fetch:
                article = wiki.fetch_wiki_patch_note()

        browser_fetch.assert_called_once_with(wiki.WIKI_URL)
        self.assertEqual(article["title"], "Browser update")

    def test_retryable_522_is_retried_before_browser(self):
        responses = [
            FakeResponse("upstream error", status_code=522),
            FakeResponse(valid_wiki_html("Recovered over HTTP")),
        ]
        with patch.object(wiki.requests, "get", side_effect=responses):
            with patch.object(wiki.time, "sleep"):
                with patch.object(wiki, "_fetch_wiki_html_browser") as browser_fetch:
                    article = wiki.fetch_wiki_patch_note()

        browser_fetch.assert_not_called()
        self.assertEqual(article["title"], "Recovered over HTTP")

    def test_failure_notifications_are_thresholded_and_cooled_down(self):
        state = {}
        with patch.object(wiki.bot, "send_debug") as send_debug:
            with patch.object(wiki.time, "time", side_effect=[1000, 1100, 1200, 1300]):
                wiki._record_wiki_failure(state, RuntimeError("boom 1"))
                wiki._record_wiki_failure(state, RuntimeError("boom 2"))
                wiki._record_wiki_failure(state, RuntimeError("boom 3"))
                wiki._record_wiki_failure(state, RuntimeError("boom 4"))

        self.assertEqual(send_debug.call_count, 1)
        self.assertEqual(state[wiki.WIKI_HEALTH_KEY]["consecutive_failures"], 4)

    def test_success_clears_failure_health(self):
        state = {wiki.WIKI_HEALTH_KEY: {"consecutive_failures": 4}}
        wiki._clear_wiki_failure(state)
        self.assertNotIn(wiki.WIKI_HEALTH_KEY, state)


if __name__ == "__main__":
    unittest.main()
