"""Discord native webhook embeds: opt-in, bounded, no unintended pings."""
import unittest
from datetime import datetime, timezone

from community.models import Event, World, Destination, Provenance
from community.publishers import (
    render_discord_embed, _units, _safe_discord_source_url, send_event
)

NOW=datetime(2026,11,17,12,tzinfo=timezone.utc)
DEST=Destination("discord","discord","DISCORD_WEBHOOK")
URL="https://discord.com/api/webhooks/123456789/test-only-secret"
CREDENTIALS={"DISCORD_WEBHOOK":URL}


def event(*, title="Siege news",body="Observed castle owner changed",url="https://lineage2dex.com/en/rating/new-interlude.343",
          provenance=Provenance.OBSERVED,occurs_at=None,world=None):
    return Event(
        world or World("L2Dex","New-Interlude x25"),
        "dex","event-42","castle_owner_change",title,body,url,
        provenance,NOW,occurs_at=occurs_at,
    )


class DiscordEmbedTests(unittest.TestCase):
    def test_default_is_same_plain_text_payload(self):
        calls=[]
        status=send_event(DEST,event(),"uk",CREDENTIALS,
                          lambda url,payload: calls.append(payload) or (200,b'{"id":"123456789"}'))
        self.assertTrue(status)
        self.assertIn("content",calls[0])
        self.assertNotIn("embeds",calls[0])
        self.assertEqual({"parse":[]},calls[0]["allowed_mentions"])

    def test_opt_in_has_one_native_embed_and_no_content_duplication(self):
        creds=dict(CREDENTIALS,COMMUNITY_DISCORD_EMBEDS="true")
        calls=[]
        status=send_event(DEST,event(),"uk",creds,
                          lambda url,payload: calls.append((url,payload)) or (200,b'{"id":"123456789"}'))
        self.assertTrue(status)
        self.assertEqual(1,len(calls))
        url,payload=calls[0]
        self.assertTrue(url.endswith("?wait=true"))
        self.assertEqual({"parse":[]},payload["allowed_mentions"])
        self.assertNotIn("content",payload)
        self.assertEqual(1,len(payload["embeds"]))
        embed=payload["embeds"][0]
        self.assertIn("New-Interlude x25",embed["title"])
        self.assertIn("Observed castle owner",embed["description"])
        self.assertEqual("https://lineage2dex.com/en/rating/new-interlude.343",embed["url"])
        self.assertIn("observed",embed["footer"]["text"])

    def test_long_unicode_input_within_discord_embed_limits(self):
        item=event(title="🎮"*2000, body="🐉"*5000,world=World("Huge","🐉"*1000))
        e=render_discord_embed(item)
        self.assertLessEqual(_units(e["title"]),256)
        self.assertLessEqual(_units(e["description"]),4096)
        self.assertLessEqual(_units(e["footer"]["text"]),2048)
        self.assertLessEqual(sum(_units(x) for x in (e["title"],e["description"],e["footer"]["text"])),6000)

    def test_manual_and_schedule_are_not_linked_as_observed_sources(self):
        for prov in (Provenance.MANUAL,Provenance.SCHEDULED):
            with self.subTest(prov=prov):
                item=event(provenance=prov,url="https://github.com/")
                e=render_discord_embed(item)
                self.assertNotIn("url",e)
                self.assertIn(prov.value,e["footer"]["text"])

    def test_scheduled_time_is_labeled_in_utc(self):
        item=event(provenance=Provenance.SCHEDULED,
                   occurs_at=datetime(2026,11,19,17,tzinfo=timezone.utc))
        embed=render_discord_embed(item)
        self.assertEqual("Event time (UTC)",embed["fields"][0]["name"])
        self.assertIn("17:00 UTC",embed["fields"][0]["value"])

    def test_invalid_link_never_exposed_in_embed(self):
        invalid=[
            "http://example.com", "https://127.0.0.1/page",
            "https://localhost/page", "https://user:secret@example.com",
            "https://example.com/?token=SECRET", "javascript:alert(1)",
            "https://example.com:8080/path", "https://example.com/#fragment",
            "https://example.com/space here", "https://example.com/"+"x"*600,
        ]
        for url in invalid:
            with self.subTest(url=url):
                self.assertIsNone(_safe_discord_source_url(url))
                self.assertNotIn("url",render_discord_embed(event(url=url)))

    def test_failed_discord_ack_still_not_delivered(self):
        creds=dict(CREDENTIALS,COMMUNITY_DISCORD_EMBEDS="true")
        self.assertFalse(send_event(DEST,event(),"uk",creds,
                                    lambda *_:(204,b"")))
        self.assertFalse(send_event(DEST,event(),"uk",creds,
                                    lambda *_:(429,b'{"retry_after":60}')))

    def test_manual_delivery_workflow_passes_embed_var(self):
        from pathlib import Path
        base=Path(__file__).resolve().parent
        for name in ("community-bot.yml","test-community-delivery.yml"):
            data=(base/".github/workflows"/name).read_text(encoding="utf8")
            self.assertIn("vars.COMMUNITY_DISCORD_EMBEDS",data)


if __name__=="__main__":
    unittest.main()
