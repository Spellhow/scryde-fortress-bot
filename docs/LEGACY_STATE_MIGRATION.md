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


## Preserving pending news during history rotation

The legacy `process_feed_posts` previously retained only the last 50 queue entries regardless of moderation status. A busy feed could silently remove older `pending` or `approved` entries before the moderator acted.

The queue now preserves **every active pending/approved entry** and only the most recent 50 finished/expired/cancelled historical entries, while keeping their original order. New source ingestion stops before Gemini when a queue already holds **200 active entries**; the source cursor stays unchanged so fresh posts remain eligible for later retry after the backlog is moderated. This limit applies independently to the Telegram and forum/wiki news queues.

This is a conservative capacity gate. If an overloaded feed remains paused too long, the existing source backlog cap may still skip older public posts once processing resumes. Raise an operational alert and moderate the backlog; do not discard active entries to regain space. The current `site_state.json` is not rewritten by this refactor.


## Read-only replay of moderation decisions

The old News Bot and the new pure module `community/legacy_news_decisions.py` now share the same decision boundary: hold until publish time, expire aged pending posts, enforce the auto-publication grace window, or attempt publication. Explicitly approved news still bypasses automatic-expiry restrictions after its scheduled time.

To inspect a trusted copy of the current legacy state without any API calls or state writes:

```bash
python3 scripts/replay_legacy_news.py --state site_state.json --mode prod
python3 scripts/replay_legacy_news.py --state site_state.json --mode debug
python3 scripts/replay_legacy_news.py --state site_state.json --now 2000000000 --mode prod
```

Output contains only **counts per fixed action category** for `news` and `forum_news`. The `publish` category represents a candidate send, never a confirmed delivery. This script does not load bot tokens, call Gemini or Telegram, and never changes the state file. It never authorizes a production cutover.

On 2026-11-17, the tracked repository snapshot held **50 news entries and 34 forum entries**. All 84 are historical and require no action according to the replay; no active pending or approved entries are present in that snapshot. That is useful evidence for the saved state only: it does not prove parity for a live moderation queue or for newer game events.

The automated comparison includes publish/expiry boundaries, debug mode, approved posts, failed delivery and repeat runs. We still need a real authorized test destination and recorded before/after decisions for active moderator actions. A crash between an accepted Telegram message and a successful Git commit can still cause a duplicate on retry.


## Partial public Telegram checkpoint bridge (manual only)

A narrowly scoped checkpoint bridge is now available for the original **public Scryde x1000 Telegram channel** `https://t.me/s/scryde`. It is deliberately narrower than a full migration: a legacy post number is treated as a *previously handled source post*, not proof that the old bot successfully delivered it.

In a separately configured **test repository** with one `telegram_public` source whose URL is exactly the channel above and with a Telegram destination alias, inspect the existing legacy snapshot using:

```bash
python3 scripts/prepare_legacy_telegram_watermark.py   --legacy site_state.json   --config community.json   --current community_deliveries.json   --source-alias telegram-feed   --destination-alias clan-channel
```

Replace the source and destination aliases with the actual aliases in your test configuration. The command defaults to **dry run**, reads only the files and prints a redacted aggregate. It refuses an active or unknown-status moderation entry, a missing/invalid source cursor, an inconsistent sent ID, ambiguous subscriptions, the wrong world/network, or any source other than the exact original public channel.

To create a **separate candidate file for offline inspection**, explicitly add `--output candidate_state.json --confirm`. The output must not exist; the script cannot overwrite the old `site_state.json`, existing `community_deliveries.json`, or `community.json`. It preserves the current state and adds a hashed source+world+destination checkpoint key with a public integer post watermark. It contains no raw news content, chat ID, moderator identity, URLs, or bot tokens.

When a candidate state is installed by an authorized test operator, the Community Bot suppresses old `scryde/<post-number>` news events up through that watermark **only for the selected destination**. Other destinations are unaffected. A newer source post beyond the checkpoint can still be delivered. Suppressed items are counted as skipped, never as successful sends. No marker exists by default, so fresh installations behave exactly as before.

**Do not activate production BSOE based on this bridge.** It does not import forum/wiki post identities, news text, pending approvals, exact moderation decisions, owner/attack flags or Telegram callback offsets. The script always returns `cutover_authorized=false`. It also cannot verify that a destination alias resolves to the original production Telegram chat, because addresses are kept in GitHub Secrets. That must be checked independently with an authorized test channel before any deployment.

Rollback for a test copy: remove the single `legacy-tg-watermark:...` cursor entry from the candidate state, keeping the original receipt records intact; restoring the pre-test candidate backup is safer. The original tracked legacy state is never modified. Automatic cutover, forum ID mapping and per-message exact delivery provenance remain P1-STATE blockers.


## Partial public forum checkpoint bridge (manual only)

The new experimental `scryde_forum` parser can now identify official updates-thread posts as `forum-post:<post-id>`. A second opt-in checkpoint tool prepares the original legacy `forum_news.last_seen_id` for **one Telegram destination** without modifying the old state:

```bash
python3 scripts/prepare_legacy_forum_watermark.py   --legacy site_state.json   --config community.json   --current community_deliveries.json   --source-alias scryde-forum-x1000   --destination-alias clan-channel
```

This only works for the public official `board.scryde.net/threads/obnovlenija.30694` topic, a configured `Scryde/x1000` world, exactly one matching Telegram news subscription, and fully finished historical moderation records. Missing/ambiguous source IDs, pending approvals, unexpected statuses or invalid cursors **fail closed**. A different official page number keeps the same source/thread watermark identity, which prevents re-sending old IDs when an administrator updates the page URL.

Forum page-number changes preserve the source's warm-start identity too, so a new page does not silently drop its first batch of newer IDs. The default is **read-only dry run**. An explicit `--output candidate_state.json --confirm` creates a *new* candidate schema-v1 state file without overwriting any input. It preserves existing delivery receipts and source cursors, adding a distinct `legacy-forum-watermark:...` hashed key and a public integer post number. Existing Telegram-source markers can coexist in the same candidate state. No forum post texts, moderator chat/user identifiers, credentials, or source URLs are copied into the newly added marker.

On the tracked repository snapshot inspected on 2026-11-17, the forum checkpoint validated, including **36 processed forum source IDs and 34 completed queue records**. It still does not prove that posts were *delivered* rather than rejected or expired; therefore the new runner suppresses these old posts as handled without falsely acknowledging delivery. New post IDs above the saved checkpoint are eligible for normal destination-specific delivery.

**Do not use this as permission for a production cutover.** Forum/TG checkpoints are only source identity guards. Gemini content adaptation, manual approvals, callback offsets, verified owner/attack decisions, exact publication and live-channel permission smoke are still missing from the new Community Bot. Both tools report `cutover_authorized=false`. The counts shown for the *other* legacy queue mean records not processed by that individual tool, even if a previous candidate file contains the other source's marker.

Rollback: restore the pre-import candidate-state backup or remove only the new `legacy-forum-watermark:...` cursor. Preserve verified sent receipts and never rewrite tracked `site_state.json`.


## One combined public-source candidate (P1-STATE, no cutover)

The two separate read-only public-history bridges can now be prepared **together**, producing one candidate state for a single, explicitly selected Telegram destination. Both sources must be configured as enabled in `community.json`, with exact public Scryde x1000 origins and one unambiguous subscription each.

```bash
python3 scripts/prepare_bsoe_history.py \
  --legacy site_state.json --config community.json \
  --current community_deliveries.json \
  --telegram-source telegram-source --forum-source forum-source \
  --destination clan-channel
```

This **dry run** reads the old state, validates both source histories and prints only aggregate validation results. It does **not** save state. To create a **new, separate candidate JSON**, add `--output candidate_state.json --confirm`. That file must not already exist. Neither source state nor the current community state can be overwritten by this command.

The operation fails entirely if *either* legacy source contains active/unknown moderation, inconsistent IDs, a missing last-seen cursor, conflicting existing watermarks, or if a destination/source is invalid. The candidate preserves existing delivered hashes and cursors, and adds at most **two hashed source/world/destination watermark markers**; no messages, usernames, private chat IDs, moderator actions, website credentials or callback offsets are copied. The bridge does not read GitHub Actions Secrets.

A dry run on the tracked legacy state on 2026-11-17 accepted both histories and showed two new markers, **without writing files**. This only verifies structural eligibility of the tracked snapshot, not the current live data or whether old posts were actually delivered.

**Important:** `cutover_authorized=false` always. This cannot replace pending-approval moderation, event/castle ownership state, exact Gemini text, or the verification of real Telegram chat permissions. It is not a signal to enable BSOE production. Rollback: preserve the original state, discard the separate candidate JSON and revert the bridge code if needed. A real controlled migration must still compare source events and delivery decisions on authorized test channels.
