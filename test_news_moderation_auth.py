"""Legacy BSOE Telegram news controls must be moderator-chat scoped.

Entirely offline; does not contact Telegram or mutate the tracked state file.
"""
import copy
import unittest
from unittest.mock import Mock, patch

import github_runner as bot


def sample_state():
    item={
        "post_id":9999,
        "status":"pending",
        "title":"Private draft title",
        "text":"Private pending news content",
        "url":"https://example.invalid/post",
        "created_at":1900000000,
        "publish_after":1900003600,
        "debug_message_id":42,
    }
    return {
        "news":{"pending":[item],"sent_ids":[],"last_seen_id":9000},
        "forum_news":{"pending":[],"sent_ids":[],"last_seen_id":0},
        "meta":{"tg_update_offset":0},
    }


def command(name,chat=-100123456,user=101):
    return {"text":name,"chat":{"id":chat},"from":{"id":user}}


def callback(action,chat=-100123456,user=101):
    return {
        "id":"callback-id",
        "data":"news:{}:news:9999".format(action),
        "message":{"message_id":42,"chat":{"id":chat}},
        "from":{"id":user},
    }


def reply(chat=-100123456,user=101):
    return {
        "text":"+",
        "chat":{"id":chat},
        "from":{"id":user},
        "reply_to_message":{"message_id":42},
    }


class LegacyNewsAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.original_chat=bot.TG_CHAT_DEBUG
        self.original_allowlist=bot.NEWS_ADMIN_USER_IDS
        bot.TG_CHAT_DEBUG="-100123456"
        bot.NEWS_ADMIN_USER_IDS=""

    def tearDown(self):
        bot.TG_CHAT_DEBUG=self.original_chat
        bot.NEWS_ADMIN_USER_IDS=self.original_allowlist

    def test_all_commands_from_other_chat_ignored_without_leaking_queue(self):
        for command_name in (
            "/news_list",
            "/news_show news 9999",
            "/news_help",
            "/news_publish news 9999",
            "/news_cancel news 9999",
            "/news_retry news 9999",
            "/news_delay news 9999 60",
        ):
            with self.subTest(command_name=command_name):
                state=sample_state()
                before=copy.deepcopy(state)
                with patch.object(bot,"send_telegram") as send:
                    self.assertFalse(bot.handle_news_command(
                        state,command(command_name,chat=-100222222)
                    ))
                send.assert_not_called()
                self.assertEqual(before,state)

    def test_untrusted_callbacks_cannot_approve_cancel_delay_or_read(self):
        for action in ("publish","cancel","delay60","show"):
            with self.subTest(action=action):
                state=sample_state()
                before=copy.deepcopy(state)
                with patch.object(bot,"send_telegram") as send, \
                     patch.object(bot,"answer_callback_query",return_value=True) as answer:
                    self.assertTrue(bot.handle_news_callback(
                        state,callback(action,chat=-100222222)
                    ))
                self.assertEqual(before,state)
                send.assert_not_called()
                answer.assert_called_once_with("callback-id","Недостатньо прав")

    def test_untrusted_reply_shortcuts_cannot_approve(self):
        state=sample_state()
        before=copy.deepcopy(state)
        with patch.object(bot,"send_telegram") as send:
            self.assertFalse(bot.handle_news_reply_action(
                state,reply(chat=-100222222)
            ))
        self.assertEqual(before,state)
        send.assert_not_called()

    def test_missing_moderator_chat_is_not_open_access(self):
        bot.TG_CHAT_DEBUG=""
        state=sample_state()
        with patch.object(bot,"send_telegram") as send, \
             patch.object(bot,"answer_callback_query",return_value=True):
            self.assertFalse(bot.handle_news_command(
                state,command("/news_publish news 9999")
            ))
            self.assertFalse(bot.handle_news_reply_action(state,reply()))
            self.assertTrue(bot.handle_news_callback(state,callback("publish")))
        send.assert_not_called()
        self.assertEqual("pending",state["news"]["pending"][0]["status"])

    def test_optional_user_allowlist_rejects_group_members_except_ids(self):
        bot.NEWS_ADMIN_USER_IDS="101, 205"
        self.assertTrue(bot.authorized_news_moderator(-100123456,101))
        self.assertTrue(bot.authorized_news_moderator(-100123456,"205"))
        self.assertFalse(bot.authorized_news_moderator(-100123456,500))
        self.assertFalse(bot.authorized_news_moderator(-100123456,None))
        self.assertFalse(bot.authorized_news_moderator(-100222222,101))
        state=sample_state()
        with patch.object(bot,"send_telegram") as send:
            self.assertFalse(bot.handle_news_command(
                state,command("/news_publish news 9999",user=500)
            ))
        send.assert_not_called()
        self.assertEqual("pending",state["news"]["pending"][0]["status"])

    def test_malformed_allowlist_fails_closed(self):
        for value in ("101,foo","101,,205","-101","0","101 205","101;205"):
            with self.subTest(value=value):
                bot.NEWS_ADMIN_USER_IDS=value
                self.assertFalse(bot.authorized_news_moderator(-100123456,101))

    def test_authorized_chat_without_allowlist_keeps_legacy_publish(self):
        state=sample_state()
        with patch.object(bot,"send_telegram",return_value=True) as send:
            self.assertTrue(bot.handle_news_command(
                state,command("/news_publish news 9999")
            ))
        self.assertEqual("published",state["news"]["pending"][0]["status"])
        self.assertGreaterEqual(send.call_count,1)

    def test_authorized_callback_with_allowlist_can_publish(self):
        bot.NEWS_ADMIN_USER_IDS="101"
        state=sample_state()
        with patch.object(bot,"send_telegram",return_value=True) as send, \
             patch.object(bot,"answer_callback_query",return_value=True) as answer, \
             patch.object(bot,"edit_telegram_reply_markup",return_value=True):
            self.assertTrue(bot.handle_news_callback(state,callback("publish")))
        self.assertEqual("published",state["news"]["pending"][0]["status"])
        answer.assert_called_once_with("callback-id","Опубліковано")
        self.assertGreaterEqual(send.call_count,1)

    def test_authorized_reply_with_allowlist_can_publish(self):
        bot.NEWS_ADMIN_USER_IDS="101"
        state=sample_state()
        with patch.object(bot,"send_telegram",return_value=True) as send:
            self.assertTrue(bot.handle_news_reply_action(state,reply()))
        self.assertEqual("published",state["news"]["pending"][0]["status"])
        self.assertGreaterEqual(send.call_count,1)

    def test_token_bearing_get_updates_failure_is_sanitized(self):
        def fail(*args,**kwargs):
            raise RuntimeError("https://api.telegram.org/botTEST_PRIVATE_TOKEN/getUpdates")
        with patch.object(bot.requests,"get",side_effect=fail), \
             patch.object(bot,"log") as log:
            self.assertFalse(bot.process_callback_updates(sample_state()))
        logged=" ".join(str(c) for c in log.call_args_list)
        self.assertNotIn("TEST_PRIVATE_TOKEN",logged)
        self.assertIn("RuntimeError",logged)

    def test_both_legacy_workflows_pass_optional_user_allowlist(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent
        for name in ("news-bot.yml", "siege-bot.yml"):
            with self.subTest(name=name):
                yaml = (root/".github"/"workflows"/name).read_text(encoding="utf8")
                self.assertIn("NEWS_ADMIN_USER_IDS: ", yaml)
                self.assertIn("secrets.NEWS_ADMIN_USER_IDS", yaml)

    def test_callback_error_logging_does_not_expose_token(self):
        with patch.object(bot.requests,"post",side_effect=RuntimeError("botTEST_PRIVATE_TOKEN")), \
             patch.object(bot,"log") as log:
            self.assertFalse(bot.answer_callback_query("callback-id","Denied"))
        self.assertNotIn("TEST_PRIVATE_TOKEN",str(log.call_args_list))


if __name__=="__main__":
    unittest.main()
