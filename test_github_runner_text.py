"""Offline regression for model-generated and persisted visible newline escapes."""
import json
import os
import unittest

os.environ.setdefault("TG_TOKEN", "test-token")
os.environ.setdefault("TG_CHAT", "test-chat")

import github_runner as bot


class TelegramTextNormalizationTests(unittest.TestCase):
    def test_gemini_escaped_newlines_render_correctly(self):
        payload = {
            "relevant": True,
            "action": "new",
            "target_state_key": "",
            "target_post_id": 0,
            "title": "Patch",
            "text": r"<b>Patch</b>\n\n– Change one\n– Change two",
        }
        parsed = bot.parse_gemini_news_response(json.dumps(payload))
        self.assertEqual(
            "<b>Patch</b>\n\n– Change one\n– Change two", parsed["text"]
        )

    def test_pending_post_sanitizer(self):
        text = r"<b>Update</b>\n\n– Balance changes\n– Bug fixes"
        actual = bot.sanitize_telegram_html(text)
        self.assertEqual(
            "<b>Update</b>\n\n– Balance changes\n– Bug fixes", actual
        )
        self.assertNotIn(r"\n", actual)

    def test_visible_windows_carriage_return_sequence(self):
        self.assertEqual(
            "First\nSecond",
            bot.normalize_visible_newline_escapes(r"First\r\nSecond"),
        )

    def test_real_newlines_unchanged(self):
        value = "One\nTwo\n\nThree"
        self.assertEqual(value, bot.normalize_visible_newline_escapes(value))

    def test_preserve_windows_path_in_plain_news(self):
        value = r"Settings under C:\newfiles"
        self.assertEqual(value, bot.normalize_visible_newline_escapes(value))

    def test_preserve_mixed_literal_and_real_newlines(self):
        value = "Change list:\nFile C:\\newfolder"
        self.assertEqual(value, bot.normalize_visible_newline_escapes(value))

    def test_single_escaped_newline_when_no_path(self):
        self.assertEqual("Line 1\nLine 2", bot.normalize_visible_newline_escapes(r"Line 1\nLine 2"))

    def test_already_escaped_backslash_double_stays_literal(self):
        value = r"Example \\not-an-escape"
        self.assertEqual(value, bot.normalize_visible_newline_escapes(value))


if __name__ == "__main__":
    unittest.main()
