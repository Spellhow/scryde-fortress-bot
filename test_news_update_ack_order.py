"""Moderation updates are processed before the next poll acknowledges them.

No real Telegram network calls or writes to tracked BSOE state.
"""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import github_runner as bot


def sample():
    return {"meta":{"tg_update_offset":100},
            "news":{"pending":[],"sent_ids":[],"last_seen_id":0},
            "forum_news":{"pending":[],"sent_ids":[],"last_seen_id":0}}


def response(*updates):
    answer=Mock()
    answer.raise_for_status.return_value=None
    answer.json.return_value={"ok":True,"result":list(updates)}
    return answer


class TelegramAcknowledgementOrderTests(unittest.TestCase):
    def test_update_is_processed_before_advancing_local_cursor(self):
        state=sample()
        update={"update_id":100,"callback_query":{"id":"id","data":"news:show:news:9"}}
        observed=[]
        def handle(*args):
            observed.append(state["meta"]["tg_update_offset"])
            return True
        with patch.object(bot.requests,"get",return_value=response(update)) as get, \
             patch.object(bot,"handle_news_callback",side_effect=handle):
            self.assertTrue(bot.process_callback_updates(state))
        self.assertEqual([100],observed)
        self.assertEqual(101,state["meta"]["tg_update_offset"])
        get.assert_called_once()
        self.assertEqual(100,get.call_args.kwargs["params"]["offset"])

    def test_multiple_updates_advance_only_after_all_actions(self):
        state=sample()
        updates=[
            {"update_id":100,"message":{"text":"/news_list"}},
            {"update_id":101,"callback_query":{"id":"id","data":"news:show:news:9"}},
        ]
        observed=[]
        def msg(_state,_message):
            observed.append(("message",state["meta"]["tg_update_offset"]))
            return True
        def callback(_state,_callback):
            observed.append(("callback",state["meta"]["tg_update_offset"]))
            return True
        with patch.object(bot.requests,"get",return_value=response(*updates)) as get, \
             patch.object(bot,"handle_news_callback",side_effect=callback), \
             patch.object(bot,"handle_news_reply_action",return_value=False), \
             patch.object(bot,"handle_news_command",side_effect=msg):
            self.assertTrue(bot.process_callback_updates(state))
        self.assertEqual([("message",100),("callback",100)],observed)
        self.assertEqual(102,state["meta"]["tg_update_offset"])
        get.assert_called_once()

    def test_handler_failure_does_not_ack_or_advance(self):
        state=sample()
        original=copy.deepcopy(state)
        update={"update_id":100,"callback_query":{"id":"id","data":"news:publish:news:9"}}
        with patch.object(bot.requests,"get",return_value=response(update)) as get, \
             patch.object(bot,"handle_news_callback",side_effect=RuntimeError("processing failed")):
            with self.assertRaises(RuntimeError):
                bot.process_callback_updates(state)
        self.assertEqual(original,state)
        get.assert_called_once()

    def test_failed_first_handler_update_replayed_from_same_offset(self):
        state=sample()
        update={"update_id":100,"callback_query":{"id":"id","data":"news:publish:news:9"}}
        requests=[]
        def fetch(url,**kwargs):
            requests.append(kwargs["params"]["offset"])
            return response(update)
        attempts=[]
        def handler(_state,_cb):
            attempts.append(len(attempts)+1)
            if len(attempts)==1:
                raise RuntimeError("worker interrupted")
            return True
        with patch.object(bot.requests,"get",side_effect=fetch), \
             patch.object(bot,"handle_news_callback",side_effect=handler):
            with self.assertRaises(RuntimeError):
                bot.process_callback_updates(state)
            self.assertEqual(100,state["meta"]["tg_update_offset"])
            self.assertTrue(bot.process_callback_updates(state))
        self.assertEqual([100,100],requests)
        self.assertEqual(101,state["meta"]["tg_update_offset"])
        self.assertEqual(2,len(attempts))

    def test_empty_api_batch_leaves_cursor_untouched(self):
        state=sample()
        with patch.object(bot.requests,"get",return_value=response()) as get:
            self.assertFalse(bot.process_callback_updates(state))
        get.assert_called_once()
        self.assertEqual(100,state["meta"]["tg_update_offset"])

    def test_failed_fetch_keeps_cursor_and_hides_exception_message(self):
        state=sample()
        with patch.object(bot.requests,"get",side_effect=RuntimeError("secret-bot-token")), \
             patch.object(bot,"log") as log:
            self.assertFalse(bot.process_callback_updates(state))
        self.assertEqual(100,state["meta"]["tg_update_offset"])
        self.assertNotIn("secret-bot-token",str(log.call_args_list))

    def test_untrusted_callback_consumed_without_publication(self):
        old_chat=bot.TG_CHAT_DEBUG
        bot.TG_CHAT_DEBUG="-100111"
        state=sample()
        update={
            "update_id":100,
            "callback_query":{
                "id":"forged",
                "data":"news:publish:news:9",
                "message":{"chat":{"id":-100222},"message_id":1},
                "from":{"id":42},
            },
        }
        try:
            with patch.object(bot.requests,"get",return_value=response(update)) as get, \
                 patch.object(bot,"answer_callback_query",return_value=True) as answer, \
                 patch.object(bot,"send_telegram") as send:
                self.assertTrue(bot.process_callback_updates(state))
            self.assertEqual(101,state["meta"]["tg_update_offset"])
            send.assert_not_called()
            answer.assert_called_once_with("forged","Недостатньо прав")
            get.assert_called_once()
        finally:
            bot.TG_CHAT_DEBUG=old_chat

    def test_cursor_serializable_for_following_poll_ack(self):
        state=sample()
        update={"update_id":100,"message":{"text":"unrelated"}}
        with patch.object(bot.requests,"get",return_value=response(update)), \
             patch.object(bot,"handle_news_reply_action",return_value=False), \
             patch.object(bot,"handle_news_command",return_value=False):
            self.assertFalse(bot.process_callback_updates(state))
        persisted=json.loads(json.dumps(state))
        self.assertEqual(101,persisted["meta"]["tg_update_offset"])


if __name__=="__main__":
    unittest.main()
