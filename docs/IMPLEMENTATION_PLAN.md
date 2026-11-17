# Implementation plan: Scryde Fortress Bot to Lineage 2 Community Bot

Status: **approved direction; implementation in progress**. Owner decision 2026-11-16: **GitHub-only first**. This document is a task contract for coding agents, not a statement that future features already exist.

## Outcome and non-negotiables
An admin can deploy the bot from a GitHub template, configure a Lineage 2 world/clan, connect an authorized Telegram destination and receive tracked events and filtered news. The standard install does not need VPS, Docker, a database service, a web UI or paid AI. More reliable dispatch and Discord interactions may use optional self-hosting.

Preserve the working Scryde x1000 + BSOE flows: fortress/castle defense, clan attacks, cancellation/loss, early reminders, news and wiki adaptation, Gemini-assisted Ukrainian posts, moderation queue, deduplication, debug alerts, and watchdog. Existing deployments must have a migration/rollback path.

**Constraints**
- GitHub Actions scheduled jobs can be delayed or disabled after inactivity. Never promise precise alert times in GitHub-only mode.
- Differentiate the **game network**, **world/server**, **chronicle/ruleset**, **clan** and **destination**.
- Pull news/HTML/API once per source, normalize once, then fan out to subscribed destinations. Keep platform formatting separate.
- No unapproved scraping, private-channel reading, SSRF, exposed tokens, or uncontrolled external URLs.
- AI must not invent castle owners, raid boss kills, times, rewards, patch contents or promo codes. Failed AI must not silently publish fabricated content.
- Explicitly classify event provenance: `observed`, `scheduled`, `manual`; note confidence and timestamp.
- Budget GitHub Actions minutes, API calls, and Git commit churn; avoid extra hosted CI for docs-only changes.
- No breaking changes to the original BSOE installation without tests and owner-aware rollout.

## Milestone tracker

### P0-BASE: baseline audit and repository hygiene (first PR)
- [x] Set truthful GitHub description and topics (the current Scryde bot, not unreleased Discord features).
- [x] Add this agent plan and `AGENTS.md`.
- [x] Correct README: two workflows, VPS dispatcher today, opt-in GitHub-only schedule, existing functionality and limitations.
- [x] Add offline pull-request CI (no browser install, network scraping or real credentials).
- [x] Add explicit security and contributor/deployment notes.
- [x] Add a license for repository code; audit dependency and asset licenses before redistributing bundled artifacts.
- [x] Add workflow-contract regression test for schedule gating.
- [ ] Audit tracked files and *history* for credentials and personal identifiers, document verified findings; if historical leakage is found, rotate first and coordinate removal. **Pattern scans completed** (169 historical code/config blobs + 5,973 state versions, no regex matches); non-standard identifiers/human privacy review still pending (see security audit).
- [ ] Add fixtures for malformed siege rows, multi-object ownership, re-registrations, pending news expiry and idempotent publication; reuse existing tests. Malformed/duplicate rows, multi-object fixtures and false cancellation/loss regressions now covered; complete all re-registration/news replay parity before closing. Legacy Gemini JSON visible-newline normalization and saved pending text tests are now added; approval/expiry/replay parity remains open. Published news posts can no longer be reopened by /news_retry, and previously handled source IDs are filtered before Gemini calls. Failed negative BSOE delivery (loss/cancellation) now remains retryable after mock transport failure.
- [x] Inventory configuration globals in `github_runner.py`, `fortress_bot.py` and both workflows; separate operational secrets from reusable defaults. See `docs/CONFIG_INVENTORY.md`; the next milestone introduces versioned multi-community config.
- [ ] Verify production workflows after merging without enabling extra scheduled jobs for the VPS deployment. Note: as of 2026-11-16 the VPS dispatcher timer was disabled and the last News/Siege workflows ran on 2026-10-19; do not re-enable without checking the owner's intent.

**P0 acceptance**: offline suite passes, runtime workflows have unchanged behavior unless `RUN_GITHUB_SCHEDULE=true`, no credentials leaked by new files, README matches reality, and the BSOE owner confirms existing dispatch continues. Do not mark P0 complete just because this first PR merges.

### P0-SCHEDULE: self-contained GitHub-only starter
- [x] Add an *opt-in* 10-minute scheduled trigger to both existing workflows. A repository variable `RUN_GITHUB_SCHEDULE=true` enables jobs for schedule events, while manual/VPS `workflow_dispatch` remains available.
- [ ] Exercise the opt-in path in a disposable/test repository and verify news/siege dedupe, secrets, workflow permissions, state persistence and recovery. Clean Community Bot setup/dry-run/baseline passed; simulated Telegram/Discord ack-failure and persisted retry tests added. Real outgoing sends, recovery and cron timing remain outstanding.
- [ ] Document fork/template ownership, GitHub Actions enabling and repository secrets/variables; test the full setup with a clean account. Same-owner private clean-copy smoke passed. An opt-in one-message manual delivery test now exists for independently configured communities; actual delivery and independent-account onboarding remain.
- [x] Choose GitHub template and enable its flag (2026-11-17). A clean private-repository test passed setup, live-source dry-run, first persisted baseline and valid variable creation. External Telegram/Discord delivery and cron timing are pending verification.
- [ ] Investigate Git state persistence alternatives without adding required paid hosting. Existing BSOE `site_state.json` remains; GitHub-only forks use isolated `community_state.json` (implemented). Atomic/alternate state storage still open.
- [x] Document default cadence, latency, rate limits and forked GitHub Actions quotas (see `docs/GITHUB_FIRST.md`).

**Acceptance**: fresh repository + secrets + target channel + variable + enabled Actions produces a safe test alert with no VPS; defaults leave original production unchanged.

### P1-CORE: event model and Scryde adapter
- [ ] Define typed `GameNetwork`, `World`, `Clan`, `Source`, `Event`, `Destination`, `Subscription` and provenance fields. Core `World`, `Event`, `Destination`, `Subscription`, provenance are implemented; separate network/clan/source entities remain.
- [ ] Build `SourceAdapter` interface: `fetch/parse/normalize`, source IDs, revision and normalized event keys. Stateless parse/normalize Protocol exists; common fetching and health remain.
- [ ] Extract Scryde fortress/castle parsing to a module without changing event semantics. Shared stdlib row trust/attacker parser now used by **legacy runner, shadow projection and new Scryde adapter**, preserving helper compatibility. Ownership/attack decision engine and publishing remain legacy until complete parity testing. Core siege alert eligibility checks (defence/our attack/reminder/cancellation/expiry) are now shared pure functions used by both the legacy sender and shadow; state transitions, copy and publishing are still legacy.
- [ ] Extract news ingestion, Gemini formatting, moderation, template rendering and delivery into tested modules. Legacy Telegram polling no longer pre-acknowledges unprocessed moderator updates; offline replay/cursor tests cover interruptions, and the old queue hold/expire/publish policy is now a pure shared module with a read-only replay CLI, tracked-state audit and deterministic legacy-runtime parity tests. Gemini formatting, message copy, live moderation and full modularization remain.
- [ ] Enforce shared source polling, publication idempotency per destination and safe retries. New community runner fetches each source once, isolates failed destinations and retries unsent items on later snapshots; legacy BSOE cutover and idempotent remote edits remain.
- [ ] Add source-level backoff/health and check that anti-bot challenges do not imply a lost fortress. Cross-run HTTP failure backoff (20→40→80→120 minutes) stored as hashed URL health markers has been added for the new Community Bot; parser-specific failures and legacy BSOE source health/parity remain pending.
- [ ] Compare old and new Scryde outputs in read-only shadow mode on representative cases before cutover. Candidate-event projector and deterministic comparison against mocked legacy sends implemented; read-only decision-type logging is opt-in. Exact message copy, real observed input parity and production cutover remain open (see docs/SCRYDE_SHADOW.md).

**Acceptance**: identical BSOE event decisions and news publication policies, full offline tests, rollback by configuration.

### P1-STATE: durable state without required hosting
- [ ] Define a versioned state schema and atomic update strategy for GitHub-only (workflow concurrency + conflict-aware commits). Community v1 JSON and atomic local writes exist; state persistence now three-way merges independent receipts on concurrent Git advances and refuses incompatible cursors. Offline bare-Git race tests verify this. Legacy migration and crash limitations remain.
- [ ] Preserve sent/pending IDs and latest observed ownership through migration; include migration and rollback scripts with dry-run mode. Added read-only `scripts/legacy_state_preflight.py` with no-secret aggregate inventory, explicit blockers and tests. Legacy active pending/approved news entries now survive history rotation; finished history remains capped at 50, and new ingestion pauses at 200 active items to avoid silent data loss. Read-only replay against the tracked state confirms 84 historical entries and no current moderation actions in that snapshot. A manual opt-in **partial public Telegram watermark bridge** now maps old handled post numbers to one hashed source/world/destination cursor; it refuses active moderation, untrusted source URLs, and ambiguous config. Runtime honors the marker only for that destination, with offline replay tests. Both original public Scryde Telegram and official forum post-number checkpoints now have explicit dry-run-first, destination-scoped partial import tools; real tracked-state verification and multi-channel replay tests are present. Legacy wiki IDs, moderation/text import, exact publication provenance, live parity and production rollback remain.
- [x] Add a combined all-or-nothing, dry-run-first candidate generator for BSOE public Telegram plus Scryde forum checkpoints (`scripts/prepare_bsoe_history.py`), preserving existing receipts and refusing active moderation. Tracked legacy state dry run passed; production cutover remains blocked by full moderation/ownership/delivery parity.
- [ ] Prevent repeated AI processing and repeated sends across retries, crashes and concurrent deliveries.
- [ ] For optional always-on mode, offer SQLite with a single writer; later PostgreSQL only when operationally justified.
- [ ] Eliminate per-run Git commits when there are no changes; measure Git churn and retention.
- [ ] Review public state for potentially sensitive user-specific data *before* adding multi-tenancy. Never commit private community configuration.

**Acceptance**: old state imports deterministically, no duplicate posts under replay tests, GitHub-only needs no external DB.

### P1-CONFIG: multi-community Telegram setup
- [x] Introduce a versioned YAML/JSON config and validate network/world/chronicle/clan independently. Versioned JSON parser and example implemented; interactive setup remains open.
- [ ] Support multiple Telegram destinations with isolated subscription filters and correct publication permissions. Case-insensitive destination/source alias collisions now rejected, in-run failed overlapping sends attempted once, and ambiguous language rules rejected. Offline fan-out tested; live permission verification and real multi-channel smoke pending.
- [ ] Add CLI / Telegram admin-only setup as a progressive enhancement; keep a secrets-based starter setup. One-time GitHub Actions and CLI setup generators now exist; Telegram chat-driven setup remains open.
- [ ] Persist destination settings outside public state unless explicitly intended; do not commit secrets or private chat IDs.
- [ ] Test a two-destination scenario: one source fetch, different language/filter, independent message IDs and failure handling.
- [ ] Document least-privilege bot permissions and admin authorization. Legacy BSOE moderation commands, callbacks and reply shortcuts now require the configured debug chat; an optional secret-based Telegram user-ID allowlist further restricts moderators. Interactive setup for independent community bots and live permissions tests remain.

**Acceptance**: two test channels with different settings receive only relevant events; a failed destination cannot block another.

### P1-L2DEX: first additional server
- [x] Verify current official/public castle ranking schema and rules of use; capture fixtures and timestamps. The 2026-11-17 public New-Interlude x25 ranking parsed nine castles; fixtures cover observed headings and fields. Recheck site rules before increasing polling frequency.
- [x] Implement an independent L2Dex adapter for world-specific owner/attacker/siege data where actually exposed. It compares tracked castle snapshots and emits only observed owner changes/new registrations. It does **not** infer a live siege or assign an unknown timezone.
- [ ] Compare observed owner changes, missing rows and unreliable data against truth; classify uncertain events.
- [x] Add tests for changed HTML, empty rankings and server/world mixups. Tests also cover initial baseline, missing rows/owners, re-registration, return to prior owner and failed delivery replay.
- [ ] Ship as opt-in, shadow first; only enable outgoing alerts after real-world verification.

**Acceptance**: Scryde and L2Dex run from same event core, no Scryde regressions, no fabricated siege signals.

### P1-FEEDS: configurable sources
- [x] Add RSS/Atom then public Telegram feeds, JSON APIs and permitted HTML pages. Stateless parsers and safe HTTP reader implemented; live scheduling/integration still open.
- [x] Add dedicated opt-in public Scryde forum parsing with stable numeric post IDs, official-thread URL allowlisting, mandatory keyword gate and offline fan-out/replay tests. Old forum moderation ID migration and real-world send parity remain open.
- [x] Preserve Scryde forum warm-start state across numbered pages; promote compatible URL-specific legacy markers to the stable thread key on the next healthy run without dropping new posts. Live source verification and full BSOE cutover still pending.
- [x] Preserve Scryde forum warm-start state across numbered pages; promote compatible URL-specific legacy markers to the stable thread key on the next healthy run without dropping new posts. Live source verification and full BSOE cutover still pending.
- [x] Require URL allowlisting/SSRF prevention (private IP, redirects, DNS rebinding, credentials in URLs, local file/metadata services). HTTPS-only public DNS verification with connection IP pinning; no redirects.
- [ ] Cap response size, timeouts, browser usage and per-domain rate. Per-request body/timeout bounds already exist; fresh in-run requests now limited to six unique URLs per host. Cross-run/provider-specific backoff and rate policy still pending.
- [ ] Provide source preview, formatting, provenance, per-server filtering and moderation choices. Read-only preview workflow and deterministic per-world source filters implemented, no sends/state mutation. Semantic classification and per-community moderation controls remain.
- [ ] Treat private Telegram and Discord sources as authenticated opt-in integrations, never scrape inaccessible data.
- [ ] Cache normalized article content and optional translations across recipients. Identical URLs now share one HTTP fetch per run, with per-world parsing and filters. Persistent normalization/translation caching remains pending.

**Acceptance**: a new public source can be configured without changing Python source; a malicious source URL is rejected.

### P1-DISCORD: optional publisher and commands
- [x] Separate Discord webhook delivery from interactive Discord bot commands. Outbound webhook transport implemented; interactive commands not implemented.
- [ ] Add channel mapping, role mention controls, permission checks, embeds and slash commands. Optional Discord rich embeds now supported behind `COMMUNITY_DISCORD_EMBEDS=true` (disabled by default), with explicit event provenance, UTC timestamp and disabled mentions. Thread/channel role mapping, permission checks and slash commands remain.
- [ ] Reuse the event store and source poller; do not run another crawler per destination.
- [ ] Document that full-time interactive commands may require an always-on process; GitHub-only supports scheduled outbound notifications first.
- [ ] Test missing permissions, rate limits, duplicates and stale token behavior. Offline Telegram/Discord response contracts (2xx with message ID, 429/permission/malformed failures) and restart/replay tests added; live authorized channel/webhook smoke remains.

**Acceptance**: identical event semantics in Telegram and Discord, with platform-native formatting.

### P1-TIMERS / P2-EXTENSIONS
- [ ] Support `observed` boss respawns only with trustworthy source data; otherwise manual/scheduled timers are explicitly labeled. **Manual schedule-only reminders are implemented**, but observed boss respawns require a separately verified source.
- [ ] Optional reminders before sieges and recurring events with world timezone conversion. One-off, offset-aware manual reminder windows are implemented; verified siege schedules, recurrence and time zone ID handling remain.
- [ ] Evaluate L2 Reborn, Masterwork/MW Essence, Warland and Asterios only after validating legal and technical access to live data.
- [ ] Add optional read-only status dashboards and server/community analytics after the core is stable.
- [ ] Prepare template release, screenshots, example configs, issue templates, contributor guide and tagged version.

## Proposed boundaries (incremental, not a mandatory mass rename)
```text
app/
  core/          # event models, schedule, dedupe, subscriptions
  sources/       # scryde, l2dex, RSS, public Telegram, JSON/HTML
  services/      # siege, news, timers, optional Gemini
  publishers/    # Telegram, Discord
  moderation/    # per-destination pending/approve/reject
  storage/       # GitHub state strategy, optional SQLite
  config/        # validation and migrations
tests/           # recorded fixtures and offline regression
docs/            # installation, security, supported sources
.github/workflows/
```
Avoid moving all existing files at once. Introduce adapters and compat shims per PR.

## PR execution order and gates
1. **PR-01** P0 baseline docs/security/CI/opt-in schedule (no live behavior change by default).
2. **PR-02** P0 security/history audit and baseline regression fixtures; compatibility-safe configuration extraction.
3. **PR-03** GitHub-only clean-install test and template onboarding.
4. **PR-04** Event model + Scryde parser adapter (shadow mode).
5. **PR-05** Versioned state and dedupe migration.
6. **PR-06** Multi-destination Telegram subscriptions.
7. **PR-07** L2Dex adapter (opt-in).
8. **PR-08** Configurable feeds with validation.
9. **PR-09** Discord outbound; interactive commands as a separate optional subtask.
10. **PR-10+** raid/event timers, more validated worlds, presentation and release.

Every PR must document: *why now, touched runtime paths, before/after behavior, deterministic tests, resources/Actions-minute impact, safe rollout, rollback, accepted limitations*. Keep checklist items unchecked until verified on a relevant target.

## Risk register
- **Schedule delay**: GitHub cron is best effort; expose freshness timestamp and warn on time-critical alerts.
- **Git write contention**: `site_state.json` is shared by workflows. Preserve concurrency and optimistic state update.
- **AI cost**: free-tier model IDs alone cannot guarantee zero billing; key must be from free-tier project without billing.
- **Source volatility**: anti-bot/HTML changes need parser diagnostics, fixtures and backoff, never synthetic events.
- **Multi-tenancy**: avoid leaking private chat IDs, user preferences or chat content to a public repo.
- **Discord**: outbound webhooks suit GitHub-only; interactive commands need an always-on gateway or supported interaction endpoint.
- **License/attribution**: audit third-party fonts/images/dependencies before redistributing any bundled copyrighted assets.
