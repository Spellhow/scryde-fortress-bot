import unittest
from unittest import mock

import github_runner as bot


def make_state(item):
    return {
        "news": {"last_seen_id": 0, "sent_ids": [], "pending": [item]},
        "forum_news": {"last_seen_id": 0, "sent_ids": [], "pending": []},
    }


def make_item(now, *, status="pending", publish_late_minutes=0):
    return {
        "post_id": 9999,
        "title": "Test news",
        "text": "Body",
        "url": "https://example.invalid/post",
        "created_at": now - 2 * 60 * 60,
        "publish_after": now - publish_late_minutes * 60,
        "status": status,
        "debug_message_id": None,
        "source": "telegram",
    }


class PendingAutoPublishWindowTest(unittest.TestCase):
    def setUp(self):
        self.now = 2_000_000_000
        self.saved = {
            "target": bot.NEWS_TARGET_CHAT,
            "grace": bot.NEWS_AUTO_PUBLISH_GRACE_MIN,
            "expire": bot.NEWS_PENDING_EXPIRE_HOURS,
            "chat": bot.TG_CHAT,
            "debug": bot.TG_CHAT_DEBUG,
        }
        bot.NEWS_TARGET_CHAT = "prod"
        bot.NEWS_AUTO_PUBLISH_GRACE_MIN = 30
        bot.NEWS_PENDING_EXPIRE_HOURS = 24
        bot.TG_CHAT = "prod-chat"
        bot.TG_CHAT_DEBUG = ""

    def tearDown(self):
        bot.NEWS_TARGET_CHAT = self.saved["target"]
        bot.NEWS_AUTO_PUBLISH_GRACE_MIN = self.saved["grace"]
        bot.NEWS_PENDING_EXPIRE_HOURS = self.saved["expire"]
        bot.TG_CHAT = self.saved["chat"]
        bot.TG_CHAT_DEBUG = self.saved["debug"]

    def run_queue(self, item):
        state = make_state(item)
        with mock.patch.object(bot.time, "time", return_value=self.now), \
                mock.patch.object(bot, "send_telegram", return_value=True) as send:
            bot.process_pending_news_queue(state)
        return state["news"]["pending"][0], send

    def test_pending_inside_grace_is_published(self):
        result, send = self.run_queue(make_item(self.now, publish_late_minutes=29))
        self.assertEqual("published", result["status"])
        send.assert_called_once()

    def test_pending_outside_grace_expires_without_publish(self):
        result, send = self.run_queue(make_item(self.now, publish_late_minutes=31))
        self.assertEqual("expired", result["status"])
        send.assert_not_called()

    def test_explicit_approval_can_publish_late(self):
        result, send = self.run_queue(
            make_item(self.now, status="approved", publish_late_minutes=180)
        )
        self.assertEqual("published", result["status"])
        send.assert_called_once()

    def test_future_pending_stays_pending(self):
        result, send = self.run_queue(make_item(self.now, publish_late_minutes=-5))
        self.assertEqual("pending", result["status"])
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
