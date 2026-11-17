"""Legacy Scryde news replay and explicit retry safety, no AI/network."""
import copy
import unittest
from unittest.mock import patch

import github_runner as bot

NOW=2000000000


def item(status):
    return {
        "post_id":100,
        "status":status,
        "title":"News",
        "text":"Body",
        "url":"https://example.invalid/news",
        "created_at":NOW-120,
        "publish_after":NOW-60,
        "debug_message_id":None,
        "source":"telegram",
    }


def state(status="published"):
    return {
        "news":{"last_seen_id":99,"sent_ids":[100],"pending":[item(status)]},
        "forum_news":{"last_seen_id":0,"sent_ids":[],"pending":[]},
    }


class NewsRetryIdempotencyTests(unittest.TestCase):
    def test_published_post_cannot_be_queued_again(self):
        original=state()
        before=copy.deepcopy(original)
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"send_telegram") as send:
            self.assertTrue(bot.execute_news_retry(
                original,"news",100,feedback_chat_id="-100123456"
            ))
        self.assertEqual(before,original)
        send.assert_called_once()
        self.assertIn("уже опубліковано",send.call_args.args[0])

    def test_published_post_retry_is_noop_even_without_feedback_chat(self):
        original=state()
        before=copy.deepcopy(original)
        with patch.object(bot,"send_telegram") as send:
            self.assertTrue(bot.execute_news_retry(original,"news",100))
        self.assertEqual(before,original)
        send.assert_not_called()

    def test_existing_published_post_is_not_resent_by_queue(self):
        original=state()
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"send_telegram") as send, \
             patch.object(bot,"NEWS_TARGET_CHAT","prod"):
            bot.process_pending_news_queue(original)
        self.assertEqual("published",original["news"]["pending"][0]["status"])
        send.assert_not_called()

    def test_expired_post_can_be_deliberately_reopened(self):
        original=state(status="expired")
        with patch.object(bot.time,"time",return_value=NOW), \
             patch.object(bot,"send_telegram") as send:
            self.assertTrue(bot.execute_news_retry(original,"news",100))
        entry=original["news"]["pending"][0]
        self.assertEqual("pending",entry["status"])
        self.assertEqual(NOW,entry["created_at"])
        self.assertEqual(NOW,entry["publish_after"])
        send.assert_not_called()

    def test_previously_handled_source_id_skips_extra_gemini_call(self):
        original=state()
        posts=[
            {"id":100,"text":"Processed post","url":"https://example.invalid/100"},
            {"id":101,"text":"New post","url":"https://example.invalid/101"},
        ]
        with patch.object(bot,"gemini_rewrite_x1000_news",
                          return_value={"relevant":False}) as model:
            bot.process_feed_posts(original,posts,"news","telegram")
        model.assert_called_once()
        self.assertEqual("New post",model.call_args.args[0])
        self.assertEqual(101,original["news"]["last_seen_id"])
        self.assertEqual(1,len(original["news"]["pending"]))
        self.assertEqual([100],original["news"]["sent_ids"])

    def test_only_handled_posts_do_not_call_gemini(self):
        original=state()
        posts=[{"id":100,"text":"Old","url":"https://example.invalid/100"}]
        with patch.object(bot,"gemini_rewrite_x1000_news") as model:
            bot.process_feed_posts(original,posts,"news","telegram")
        model.assert_not_called()
        self.assertEqual(100,original["news"]["last_seen_id"])

    def test_failed_new_post_keeps_cursor_after_skipped_handled_id(self):
        original=state()
        posts=[
            {"id":100,"text":"Handled post","url":"https://example.invalid/100"},
            {"id":101,"text":"Fresh post","url":"https://example.invalid/101"},
        ]
        with patch.object(bot,"gemini_rewrite_x1000_news",return_value=None) as model:
            bot.process_feed_posts(original,posts,"news","telegram")
        model.assert_called_once()
        self.assertEqual(100,original["news"]["last_seen_id"])
        self.assertEqual(1,len(original["news"]["pending"]))


if __name__=="__main__":
    unittest.main()
