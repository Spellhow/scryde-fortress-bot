import json
import os
import unittest


os.environ.setdefault("TG_TOKEN", "test-token")
os.environ.setdefault("TG_CHAT", "test-chat")

import github_runner


class TelegramTextNormalizationTests(unittest.TestCase):
    def test_gemini_response_converts_visible_newline_escapes(self):
        payload = {
            "relevant": True,
            "action": "new",
            "target_state_key": "",
            "target_post_id": 0,
            "title": "Patch",
            "text": r"First line\n\nSecond line",
        }

        parsed = github_runner.parse_gemini_news_response(json.dumps(payload))

        self.assertEqual(parsed["text"], "First line\n\nSecond line")

    def test_telegram_sanitizer_protects_saved_pending_text(self):
        dirty = r"<b>Patch</b>\n\n- First change\n- Second change"

        cleaned = github_runner.sanitize_telegram_html(dirty)

        self.assertEqual(cleaned, "<b>Patch</b>\n\n- First change\n- Second change")
        self.assertNotIn(r"\n", cleaned)

    def test_real_newlines_are_preserved(self):
        clean = "First line\n\nSecond line"

        self.assertEqual(github_runner.normalize_visible_newline_escapes(clean), clean)


if __name__ == "__main__":
    unittest.main()
