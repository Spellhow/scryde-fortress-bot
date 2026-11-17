"""No-network Telegram/Discord API acknowledgements and persisted fan-out tests."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from community.models import Destination, Event, Provenance, World
from community.publishers import (
    DISCORD_MAX_CHARS, TELEGRAM_MAX_CHARS, _units, render_plain_event, send_event
)
from community.state import DeliveryState


NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
CREDS = {
    "TG_TOKEN": "not-real-test-token",
    "TG_CHAT": "-1001111111111",
    "DISCORD_WEBHOOK": "https://discord.com/api/webhooks/123456789/test-token",
}


def example_event(*, title="News", body="Clan update", network="Scryde",
                  world="x1000", url="https://example.invalid/post"):
    return Event(
        world=World(network, world), source_id="feed", external_id="news-77",
        kind="news", title=title, body=body, source_url=url,
        provenance=Provenance.OBSERVED, observed_at=NOW,
    )


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.telegram = Destination("telegram", "telegram", "TG_CHAT", "TG_TOKEN")
        self.discord = Destination("discord", "discord", "DISCORD_WEBHOOK")
        self.event = example_event()

    def test_telegram_only_confirms_message_id(self):
        for status, reply, expected in (
            (200, b'{"ok":true,"result":{"message_id":42}}', True),
            (200, b'{"ok":true}', False),
            (200, b'{"ok":true,"result":{"message_id":true}}', False),
            (200, b'{"ok":true,"result":{"message_id":0}}', False),
            (200, b'{"ok":false}', False),
            (429, b'{"ok":false,"parameters":{"retry_after":60}}', False),
            (200, b'{"ok":true,"result":{}}', False),
            (200, b'invalid JSON', False),
        ):
            with self.subTest(status=status, reply=reply):
                actual = send_event(
                    self.telegram, self.event, "uk", CREDS,
                    post_json=lambda *_: (status, reply)
                )
                self.assertIs(expected, actual)

    def test_discord_requires_real_webhook_message_id(self):
        for status, reply, expected in (
            (200, b'{"id":"123456789"}', True),
            (201, b'{"id":"123456789"}', True),
            (204, b'', False),
            (200, b'{}', False),
            (200, b'{"id":123}', False),
            (200, b'{"id":"abc"}', False),
            (429, b'{"retry_after":0.5}', False),
            (200, b'invalid', False),
        ):
            with self.subTest(status=status, reply=reply):
                actual = send_event(
                    self.discord, self.event, "uk", CREDS,
                    post_json=lambda *_: (status, reply)
                )
                self.assertIs(expected, actual)

    def test_telegram_and_discord_headers_and_secrets(self):
        calls = []
        def fake(url, body):
            calls.append((url, body))
            if "api.telegram.org" in url:
                return 200, b'{"ok":true,"result":{"message_id":10}}'
            return 200, b'{"id":"987654"}'
        self.assertTrue(send_event(self.telegram, self.event, "uk", CREDS, fake))
        self.assertTrue(send_event(self.discord, self.event, "en", CREDS, fake))
        self.assertEqual(2, len(calls))
        self.assertEqual(CREDS["TG_CHAT"], calls[0][1]["chat_id"])
        self.assertEqual({"parse":[]}, calls[1][1]["allowed_mentions"])
        self.assertTrue(calls[1][0].endswith("?wait=true"))
        self.assertTrue(calls[1][0].startswith(CREDS["DISCORD_WEBHOOK"]))

    def test_discord_rejects_nonofficial_or_malformed_webhook(self):
        for invalid in (
            "http://discord.com/api/webhooks/123/secret",
            "https://discord.com.evil.invalid/api/webhooks/123/secret",
            "https://discord.com/api/webhooks/123",
            "https://discord.com/api/webhooks/a/secret",
            "https://discord.com/api/webhooks/123/secret?wait=false",
            "https://discord.com:444/api/webhooks/123/secret",
            "https://user@discord.com/api/webhooks/123/secret",
        ):
            with self.subTest(invalid=invalid):
                env=dict(CREDS, DISCORD_WEBHOOK=invalid)
                self.assertFalse(send_event(
                    self.discord, self.event, "uk", env,
                    lambda *_: self.fail("malformed webhooks cannot call network")
                ))

    def test_missing_credentials_do_not_invoke_transport(self):
        for target in (self.telegram, self.discord):
            self.assertFalse(send_event(
                target, self.event, "uk", {},
                lambda *_: self.fail("no credentials: must not post")
            ))

    def test_exception_text_cannot_escape_to_router(self):
        class TokenizedError(RuntimeError):
            pass
        def fail(*_):
            raise TokenizedError("https://discord.com/api/webhooks/123/SECRET")
        self.assertFalse(send_event(self.discord, self.event, "uk", CREDS, fail))

    def test_message_size_conservative_with_emoji_and_long_world(self):
        long_event = example_event(
            title="🎮" * 1000,
            body="🐉"*4000,
            world="💥"*2000,
            url="https://example.invalid/"+"x"*3000,
        )
        for limit in (DISCORD_MAX_CHARS, TELEGRAM_MAX_CHARS, 25):
            message=render_plain_event(long_event, limit)
            self.assertLessEqual(_units(message), limit)
            self.assertTrue(message)
            self.assertNotIn("x"*3000, message)

    def test_message_source_preserved_when_it_fits(self):
        msg = render_plain_event(self.event, DISCORD_MAX_CHARS)
        self.assertIn("https://example.invalid/post", msg)
        self.assertIn("Clan update", msg)

    def test_manual_reminder_has_no_fake_source(self):
        e = example_event()
        manual = Event(
            e.world, e.source_id, e.external_id, e.kind,
            e.title, e.body, "https://github.com/",
            Provenance.MANUAL, NOW
        )
        self.assertNotIn("github.com", render_plain_event(manual, DISCORD_MAX_CHARS))


class DeliveryRoundTripTests(unittest.TestCase):
    def test_mocked_api_network_then_disk_restart_retries_only_failed(self):
        from community.config import parse_config
        from community.runner import run
        world = {"network":"Scryde", "name":"x1000"}
        config = parse_config({
            "version":1,
            "sources":[{"id":"feed", "kind":"rss", "world":world,
                        "url":"https://example.invalid/news"}],
            "destinations":[
                {"id":"telegram", "kind":"telegram", "address_env":"TG_CHAT", "token_env":"TG_TOKEN"},
                {"id":"discord", "kind":"discord", "address_env":"DISCORD_WEBHOOK"},
            ],
            "subscriptions":[
                {"destination_id":"telegram", "world":world, "source_ids":["feed"]},
                {"destination_id":"discord", "world":world, "source_ids":["feed"]},
            ],
        })
        def xml(*ids):
            return "<rss><channel>" + "".join(
                "<item><guid>id-{}</guid><title>News {}</title>"
                "<description>Text {}</description>"
                "<link>https://example.invalid/{}</link></item>".format(i,i,i,i)
                for i in ids
            ) + "</channel></rss>"

        def send_status(target, event, lang, env, ack):
            return send_event(target, event, lang, env,
                              post_json=lambda *_: ack[target.kind])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"community_deliveries.json"
            state=DeliveryState()
            initial = run(config, state, fetch=lambda _:xml(1),
                          send=lambda *args: self.fail("warm start must not send"),
                          credentials=CREDS, now=NOW)
            self.assertEqual(0, initial.sent)
            state.save(path)
            state=DeliveryState.load(path)
            acknowledgements={
                "telegram": (200,b'{"ok":true,"result":{"message_id":17}}'),
                "discord": (429,b'{"retry_after":1}')
            }
            attempts=[]
            def post(target,event,lang,env):
                attempts.append((target.id,event.external_id))
                return send_status(target,event,lang,env,acknowledgements)
            result = run(config,state,fetch=lambda _:xml(1,2),
                         send=post,credentials=CREDS,now=NOW)
            self.assertEqual(1,result.sent)
            self.assertEqual(1,len(result.errors))
            self.assertEqual([("telegram","id-2"),("discord","id-2")],attempts)
            state.save(path)
            state=DeliveryState.load(path)
            acknowledgements["discord"]=(200,b'{"id":"9999999999"}')
            attempts.clear()
            retried=run(config,state,fetch=lambda _:xml(1,2),send=post,
                        credentials=CREDS,now=NOW)
            self.assertEqual(1,retried.sent)
            self.assertEqual([("discord","id-2")],attempts)
            state.save(path)
            third=run(config,DeliveryState.load(path),fetch=lambda _:xml(1,2),send=post,
                      credentials=CREDS,now=NOW)
            self.assertEqual(0,third.sent)
            self.assertEqual([("discord","id-2")],attempts)
            raw=path.read_text()
            self.assertNotIn("not-real-test-token",raw)
            self.assertNotIn("-1001111111111",raw)
            self.assertNotIn("test-token",raw)


if __name__ == "__main__":
    unittest.main()
