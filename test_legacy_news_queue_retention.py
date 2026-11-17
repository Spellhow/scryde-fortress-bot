"""Active legacy moderation must not disappear as historical feed rows grow.

Offline, no Telegram, no public Scryde fetch or Gemini invocation.
"""
import copy
import unittest
from unittest.mock import patch

from community.legacy_news_queue import (
    MAX_ACTIVE_NEWS_ITEMS, active_moderation_count, retain_news_queue,
)
import github_runner as bot


def entry(post_id, status):
    return {
        "post_id":post_id,
        "status":status,
        "title":"News {}".format(post_id),
        "text":"Prepared moderation text",
        "url":"https://example.invalid/{}".format(post_id),
        "created_at":2000000000,
        "publish_after":2000002000,
        "debug_message_id":None,
        "source":"telegram",
    }


def state(items, last_seen=3000):
    return {
        "news":{"pending":items,"last_seen_id":last_seen,"sent_ids":[]},
        "forum_news":{"pending":[],"last_seen_id":0,"sent_ids":[]},
    }


class LegacyNewsQueueRetentionTests(unittest.TestCase):
    def test_all_pending_and_approved_survive_more_than_50_history_rows(self):
        items=[entry(i,"pending" if i%2 else "approved") for i in range(120)]
        items += [entry(i,"published") for i in range(120,210)]
        original=copy.deepcopy(items)
        result=retain_news_queue(items)
        self.assertEqual(170,len(result))
        self.assertEqual(120,active_moderation_count(result))
        self.assertEqual(list(range(120)),[x["post_id"] for x in result[:120]])
        self.assertEqual(list(range(160,210)),[x["post_id"] for x in result[120:]])
        self.assertEqual(original,items)

    def test_expired_cancelled_and_published_are_historical(self):
        items=[entry(i,s) for i,s in enumerate(
            ["cancelled","expired","published","pending","approved","ignored","published"]
        )]
        kept=retain_news_queue(items,history_limit=2)
        self.assertEqual([3,4,5,6],[item["post_id"] for item in kept])

    def test_legacy_ingestion_does_not_drop_old_active_items(self):
        items=[entry(i,"pending") for i in range(70)]
        items += [entry(i,"published") for i in range(70,135)]
        current=state(items)
        old_pending=copy.deepcopy(items[:70])
        source=[{"id":3001,"text":"New update","url":"https://example.invalid/new"}]
        with patch.object(bot,"gemini_rewrite_x1000_news",
                          return_value={"relevant":True,"title":"Update",
                                        "text":"Processed news","action":"new"}) as model, \
             patch.object(bot,"TG_CHAT_DEBUG",""):
            bot.process_feed_posts(current,source,"news","telegram")
        model.assert_called_once()
        survivors=current["news"]["pending"]
        self.assertEqual(71,active_moderation_count(survivors))
        self.assertEqual(old_pending,survivors[:70])
        self.assertEqual(3001,survivors[-1]["post_id"])
        self.assertEqual(list(range(85,135)),
                         [item["post_id"] for item in survivors[70:-1]])
        self.assertEqual(3001,current["news"]["last_seen_id"])

    def test_full_moderation_queue_defers_new_posts_without_model_call(self):
        current=state([entry(i,"pending") for i in range(MAX_ACTIVE_NEWS_ITEMS)])
        before=copy.deepcopy(current)
        with patch.object(bot,"gemini_rewrite_x1000_news") as model, \
             patch.object(bot,"log") as log:
            bot.process_feed_posts(current,[
                {"id":3001,"text":"New update","url":"https://example.invalid/new"}
            ],"news","telegram")
        model.assert_not_called()
        self.assertEqual(before,current)
        self.assertTrue(any("moderation queue full" in str(call) for call in log.call_args_list))

    def test_already_handled_source_ids_advance_cursor_even_when_queue_full(self):
        current=state([entry(i,"approved") for i in range(MAX_ACTIVE_NEWS_ITEMS)])
        current["news"]["sent_ids"]=[3001]
        with patch.object(bot,"gemini_rewrite_x1000_news") as model:
            bot.process_feed_posts(current,[
                {"id":3001,"text":"Already consumed","url":"https://example.invalid"}
            ],"news","telegram")
        model.assert_not_called()
        self.assertEqual(3001,current["news"]["last_seen_id"])
        self.assertEqual(MAX_ACTIVE_NEWS_ITEMS,active_moderation_count(current["news"]["pending"]))

    def test_malformed_status_does_not_break_retention(self):
        items=[entry(1,"pending"),{"post_id":2,"status":["invalid"]},
               {"post_id":3,"status":None},entry(4,"published")]
        result=retain_news_queue(items,history_limit=1)
        self.assertEqual([1,4],[item["post_id"] for item in result])

    def test_invalid_retention_input_or_limits_rejected(self):
        with self.assertRaises(ValueError):
            retain_news_queue("not a list")
        for limit in (-1,2.5,True):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                retain_news_queue([],history_limit=limit)

    def test_active_items_in_different_state_sections_are_isolated(self):
        telegram=retain_news_queue([entry(i,"pending") for i in range(75)])
        forum=retain_news_queue([entry(i,"published") for i in range(75)])
        self.assertEqual(75,len(telegram))
        self.assertEqual(50,len(forum))


if __name__=="__main__":
    unittest.main()
