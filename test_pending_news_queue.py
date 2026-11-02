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



class NewsLayoutRegressionTest(unittest.TestCase):
    def test_repairs_flattened_patch_notes_5086(self):
        body = (
            '🚨 <b>Велике оновлення на Scryде!</b> Патч уже встановлено на серверах x1000. '
            '✨ <b>Головне з патчноуту:</b> '
            '– Переглянуто гілки талантів <b>Берсерк</b>, <b>Страж</b> та <b>Майстер</b>. '
            '– Параметри вмінь оновлено. '
            '– Збільшено дальність <b>Escape</b>. '
            '– Розширено асортимент магазину Валерії. '
            '📜 <a href="https://a.scrd.to/patch-13.10"><b>Повний патчноут</b></a>'
        )
        fixed = bot.repair_news_layout(body)
        self.assertIn('</b>\n\nПатч уже', fixed)
        self.assertIn('x1000.\n\n✨ <b>Головне з патчноуту:</b>\n\n–', fixed)
        self.assertEqual(4, sum(line.startswith('– ') for line in fixed.splitlines()))
        self.assertIn('\n\n📜 <a href="https://a.scrd.to/patch-13.10">', fixed)
        self.assertEqual(fixed, bot.repair_news_layout(fixed))
        self.assertEqual(
            fixed + '\n\nhttps://t.me/scryde/5086',
            bot.build_news_post_message('Патч', body, 'https://t.me/scryde/5086'),
        )

    def test_keeps_preformatted_post_unchanged(self):
        body = '🎃 <b>Івент</b>\n\nУже стартує.\n\n<b>Призи:</b>\n• Один\n• Два'
        self.assertEqual(body, bot.repair_news_layout(body))

    def test_keeps_normal_one_line_post_unchanged(self):
        body = 'Нагорода – переможцям, штраф – порушникам.'
        self.assertEqual(body, bot.repair_news_layout(body))

    def test_existing_published_post_is_edited_not_reposted(self):
        item = {
            'post_id': 5086,
            'status': 'published',
            'title': 'Велике оновлення',
            'text': '<b>Зміни:</b> – Один пункт. – Другий пункт. – Третій пункт.',
            'url': 'https://t.me/scryde/5086',
        }
        state = {'news': {'pending': [item]}, 'forum_news': {'pending': []}}
        with mock.patch.object(bot, 'edit_telegram_message_text', return_value=True) as edit:
            bot.repair_published_news(state, 5086, 645)
        edit.assert_called_once()
        args = edit.call_args.args
        self.assertEqual(645, args[1])
        self.assertIn('\n–', args[2])
        self.assertIn('https://t.me/scryde/5086', args[2])
        self.assertIn('\n–', item['text'])

    def test_repair_failure_does_not_mutate_state(self):
        original = '<b>Зміни:</b> – Один. – Два. – Три.'
        item = {'post_id': 5086, 'status': 'published', 'text': original, 'url': 'https://t.me/scryde/5086'}
        state = {'news': {'pending': [item]}}
        with mock.patch.object(bot, 'edit_telegram_message_text', return_value=False):
            with self.assertRaises(RuntimeError):
                bot.repair_published_news(state, 5086, 645)
        self.assertEqual(original, item['text'])

if __name__ == "__main__":
    unittest.main()
