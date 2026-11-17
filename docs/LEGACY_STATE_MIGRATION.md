# BSOE legacy state migration preflight

The original Scryde x1000 BSOE bot still uses `site_state.json`. Its fortress/castle alert flags, outbound attack records, Telegram moderation queue, previously published news IDs, update offsets and dedupe records cannot be safely replaced by the new Community Bot's delivery-hash store without an explicit compatibility migration.

## Read-only inventory

Run this from a trusted checkout:

```bash
python3 scripts/legacy_state_preflight.py --source site_state.json
python3 scripts/legacy_state_preflight.py --source site_state.json --fail-on-blockers
```

The script parses the legacy JSON and prints **only counts and named blockers**. It never modifies files, includes message text or URLs, or prints account IDs/Telegram chat IDs. `--fail-on-blockers` returns exit code 1 when migration prerequisites are unmet. For a malformed input it exits 2 and prints only the exception category.

For reference, the tracked repository snapshot inspected on **2026-11-17** had one actively tracked fortress, zero outbound siege registrations, 50 Telegram news queue items, 34 forum/wiki queue items and 86 stored sent-source IDs (50 and 36). The report found **no currently active moderation entries**; the other queue entries were historical published, expired or other statuses. It also found a Telegram callback offset and a nonempty recent siege-alert cache.

These are aggregate counts from the repository snapshot, **not live server status** or proof that production has processed newer messages.

## Actual migration requirements (not yet implemented)

1. **Freeze and back up the exact old state**, preserving file permissions and rollback references. Never reset the old last-seen cursors to zero for an active production channel.
2. Build a deterministic mapping of every legacy `sent_ids` and `last_seen_id` to the new event identity / delivery record. Without this, news can be reposted or lost on cutover.
3. Preserve `pending`, `approved`, `published`, `expired` and dismissed news states and the moderator's authorization. New Community Bot currently has **no matching Telegram approval gateway**.
4. Import active fortress/castle ownership and attack registration flags only after comparing fresh verified public rankings against archived evidence, respecting reminder timestamps and duplicate alerts.
5. Check the Telegram update offset / callback consumer before switching gateways so moderation actions are not replayed or skipped.
6. Run both event decision engines with sending disabled on one side, compare exact notification copy and replay behavior across a real input corpus, then switch one destination at a time.
7. Keep the original `site_state.json` and legacy workflow available for rollback until a live, authorized test passes. Never silently merge legacy JSON into `community_deliveries.json`, which was designed for **public hashed delivery receipts**, not private moderation text.

**The preflight intentionally never returns `migration_ready=true` today** because the modern delivery pipeline does not implement full BSOE moderation and siege state compatibility. Avoid enabling an automatic production cutover based only on sanitized state counts.



## Replay safety for published items

The legacy `/news_retry` command cannot reopen an item marked `published`: doing so would allow a duplicate channel post on the next queue cycle. The operator should use the existing manual in-place news repair workflow when changing already published content. Expired or cancelled entries can still be deliberately retried.

When the source fetch returns a post ID already recorded in `sent_ids` but the source cursor is stale, the runner now advances that cursor without issuing another Gemini request or inserting a duplicate pending item. Failures on *new* posts still leave the cursor positioned for retry.


## Telegram moderator update acknowledgement

The legacy runner now **handles each fetched batch before advancing** `meta.tg_update_offset`. It does not issue an extra `getUpdates` call to acknowledge the batch before commands run. Telegram acknowledges the processed updates on the next poll when that stored higher offset is sent. This makes an interrupted worker more likely to replay a command instead of silently losing it before it was handled.

The updated offset is saved together with moderator state by the existing legacy state writer. A crash between a successful Telegram publication and the Git state commit can still replay the callback; the existing already-published state check mitigates subsequent duplicate sends when the state commit succeeded. This is best-effort processing, not a transactional exactly-once guarantee.

Offline tests cover callback and command order, failure before local cursor advance, re-fetch on retry, unauthorized actions, empty batches and token-safe failures.
