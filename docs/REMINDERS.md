# Manually scheduled community reminders

Status: supported by the opt-in GitHub-only Community Bot. This feature is suitable for meetings, guild coordination and **manually estimated** raid boss timers. It does not detect in-game kills, respawns, or successful sieges.

## Example

Copy and edit the disabled `scheduled_events` entry in `community.example.json` before enabling the Community Bot.

```json
{
  "scheduled_events": [{
    "id": "clan-meeting-unique-2027-01-01",
    "world": {
      "network": "L2Dex",
      "name": "New-Interlude x25",
      "chronicle": "Interlude"
    },
    "title": "Clan voice meeting",
    "body": "Join the voice channel.",
    "starts_at": "2027-01-01T20:00:00+01:00",
    "remind_before_minutes": [60, 15],
    "enabled": true
  }]
}
```

The `scheduled_events` property belongs at the root of the community JSON. An appropriate subscription references `source_ids: ["manual_schedule"]`, `event_types: ["event_reminder"]`, and the **same** game world. Set only the intended Telegram/Discord destinations.

## Timing and safety

- Every `starts_at` requires an explicit UTC offset (e.g. `+01:00`, `+02:00`, or `Z`). Naive local timestamps are rejected to avoid DST mistakes.
- Each reminder is eligible only during a **20-minute window** beginning at `starts_at - remind_before_minutes`; it will not be sent after the event's start.
- GitHub Actions community jobs request 20-minute polling, but they may run late or be skipped entirely. Short lead times such as 15 minutes can therefore be missed; a 60-minute reminder is usually more suitable.
- The same reminder will not be resent once recorded as delivered, even if GitHub retries the run. A failed destination is eligible for retry as long as its window is still open.
- Manual reminders do not require any browser, API key, data scraping, paid service, or active server.
- The event is labeled `manual`, and the message explicitly identifies it as administrator-entered, not a verified game event.
- Use a unique stable event ID for each independent occurrence; recurring schedules are **not** supported yet. To set a new date for another occurrence, assign a new ID or change `starts_at`.

Validation and unit tests live in `test_community_schedules.py` and `test_community_runner.py`. Real Telegram/Discord delivery still requires an authorized destination and a separate smoke test.
