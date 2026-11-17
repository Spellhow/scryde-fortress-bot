# Scryde Fortress Bot

An open-source Lineage 2 community bot with two compatible deployment paths: the original **BSOE / Scryde x1000** Telegram monitor, and an opt-in **GitHub-only Community Bot** for L2Dex castle changes, public news feeds, manual reminders, Telegram and Discord webhooks.

**[Use this template](https://github.com/Spellhow/scryde-fortress-bot/generate)** to create your own repository without running a VPS. The Community Bot and its setup workflow passed a clean private-repository smoke test on 2026-11-17; real outbound delivery to an authorized Telegram/Discord channel is still to be verified. See the [implementation plan](docs/IMPLEMENTATION_PLAN.md).

## Existing Scryde/BSOE capabilities

- Alerts when our fortress/castle is attacked, when our clan attacks another object, when a siege is cancelled, or ownership is lost.
- Sends pre-siege reminders and optional visual cards with castle/fortress and clan information.
- Reads Scryde rankings with Playwright Chromium (the site requires JavaScript/anti-bot handling).
- Reads [Scryde Telegram news](https://t.me/s/scryde) and Scryde Wiki patch notes, filters for x1000 and prepares Ukrainian Telegram posts with Gemini.
- Offers a Telegram debug/moderation queue with approval, delay, expiration and duplicate suppression.
- Tracks previous state in `site_state.json` and commits updates after workflow runs.
- Uses a separate VPS watchdog to detect missing GitHub Actions results in the existing production deployment.

This is a **community information bot**, not a game client or character automation tool.

## Deployment options

| Mode | Status | Server needed? | Scheduling |
| --- | --- | --- | --- |
| GitHub-only Community Bot | Verified setup + first-run baseline; outbound delivery still experimental | No | Best-effort 20-minute GitHub Actions cron |
| Legacy Scryde News/Siege | Existing workflows; VPS dispatch timer disabled at 2026-11-16 inspection | Optional VPS for dispatcher/watchdog | Manual `workflow_dispatch` or opt-in cron |

Legacy Scryde monitoring uses two workflows: [News Bot](.github/workflows/news-bot.yml) and [Siege Bot](.github/workflows/siege-bot.yml). New community installations use [Community Bot](.github/workflows/community-bot.yml) plus the one-time [setup workflow](.github/workflows/setup-community.yml). All are GitHub Actions workflows. The optional GitHub-only schedule is disabled by default and enabled with the repository variable `RUN_GITHUB_SCHEDULE=true`. In template/fork repositories, legacy Scryde workflows use `community_state.json`, while the new Community Bot keeps `community_deliveries.json`. Do **not** enable that variable for the existing VPS dispatcher unless the scheduling paths are coordinated.

### New GitHub-only community setup

1. Click [Use this template](https://github.com/Spellhow/scryde-fortress-bot/generate) and enable Actions in your repository.
2. Run **Actions → Set up Community Bot (one-time)**. Select the game network, world, public source URL and Telegram or Discord output.
3. Add repository **Secrets**: `TG_TOKEN` and `TG_CHAT` for Telegram, or `DISCORD_WEBHOOK` for Discord. The setup workflow never stores tokens in the public configuration.
4. Set repository **Variables**: `COMMUNITY_MODE=true` and initially `COMMUNITY_DRY_RUN=true`. Keep `RUN_GITHUB_SCHEDULE` unset while testing.
5. Manually run **Community Bot (GitHub-only)** to inspect the dry-run. Turn dry-run off and run once to create the initial silent baseline in `community_deliveries.json`.
6. Run **Actions → Test Community Delivery (manual)**, choose your configured destination alias and explicitly confirm sending one diagnostic message. This is disabled in the original BSOE repository. Confirm receipt before setting `RUN_GITHUB_SCHEDULE=true`.

GitHub scheduling may be delayed. Existing BSOE state remains in `site_state.json` in this source repository; fresh community installations keep an independent `community_deliveries.json`. See [complete GitHub-first setup](docs/GITHUB_FIRST.md).

## Secrets and optional AI

The new Community Bot requires **no Gemini key**. For Telegram output, configure `TG_TOKEN` and `TG_CHAT`; for Discord webhooks, configure `DISCORD_WEBHOOK`. Several destinations can share the optional `COMMUNITY_SECRETS_JSON` GitHub Secret containing environment-name-to-secret-value mappings.

Only the legacy Scryde News Bot uses `GEMINI_API_KEY` and moderation destination `TG_CHAT_DEBUG`. Keep credentials in GitHub Settings → Secrets and variables → Actions. Never commit actual tokens, private chat IDs or webhooks in `community.json`, `site_state.json` or workflows. See [configuration details](docs/CONFIG_INVENTORY.md).

The existing News Bot selects free-tier Gemini model IDs, but **zero billing additionally requires a Google AI Free Tier project with billing disabled**.

## How the existing jobs work

1. The dispatcher (VPS or opted-in GitHub cron) starts a workflow on a fresh Ubuntu runner.
2. The runner installs Python dependencies and Chromium and fetches the configured Scryde pages.
3. It compares the current siege/news data with persisted state and sends applicable Telegram messages.
4. The news flow uses moderation and delay rules. Past the configured auto-publish window, stale news expires.
5. The workflow persists any changed `site_state.json`. Both workflows share the `scryde-state` concurrency group.
6. Failures are reported to the debug chat; the VPS watchdog provides independent missing-run monitoring in the legacy deployment.

GitHub Actions scheduling is best effort. If immediate or guaranteed siege alerts are required, use a more dependable always-on dispatcher. Publishing status and event times must not be presented as guaranteed live data.

## Future multi-world core

The opt-in `community/` Python package now provides a typed world/event model, destination and subscription filters, a versioned local delivery state, and a read-only Scryde adapter for shadow testing. It is **not yet wired into the existing production bot**. See [architecture](docs/ARCHITECTURE.md).

**Shared parser milestone:** legacy BSOE and new Scryde adapters now validate ranking owner/attacker rows using one pure module; actual alert decisions and state remain legacy until parity is proven. See [Scryde shadow plan](docs/SCRYDE_SHADOW.md).

**Scryde migration progress:** the legacy runner now supports an optional *read-only shadow* of its already-fetched castle/fortress rows to evaluate the new modular core without sending notifications or changing production decisions. Disabled by default; see [shadow diagnostics and migration gates](docs/SCRYDE_SHADOW.md).

## Configurable community library (under development)

The `community/` package can now parse a versioned [example configuration](community.example.json), read public RSS/Atom, Telegram pages, JSON and selected HTML, and format outbound Telegram or Discord webhook messages. All credential references are environment-variable names. The library now has an **opt-in Community Bot workflow** for public feeds and Telegram/Discord webhooks (20-minute best-effort schedule). It does not replace live Scryde siege monitoring. Configure it from [community.example.json](community.example.json), keeping all credentials in GitHub Secrets. First runs warm-start to avoid a flood of historical posts. See [GitHub-first setup](docs/GITHUB_FIRST.md). Documentation: [source and destination design](docs/SOURCES.md).

Community output now requires a confirmed Telegram or Discord message ID before marking an event as sent, and limits long/emoji-heavy posts. See [delivery and retry contract](docs/DELIVERY_CONTRACT.md). A real authorized-channel delivery smoke test is still outstanding.

GitHub-only delivery receipts now use conflict-aware persistence: independently confirmed sends are merged if the Git branch advances, while incompatible castle/source cursor edits fail closed. See [state concurrency](docs/GITHUB_FIRST.md).

Failed public HTTPS fetches now use persistent 20–120-minute backoff across GitHub Actions runs. Cooldown skips appear in logs without generating false game alerts. See [source retry policy](docs/SOURCES.md).

Community owners can preview up to five enabled public sources without publishing anything: **Actions → Preview Community Sources (manual)**. Each job shares HTTP fetches and caps new requests at six distinct URLs per domain. See [source preview and safety limits](docs/SOURCES.md).

## Per-world news relevance (opt-in)

Public Telegram/RSS/HTML/JSON sources can now use `include_keywords` and `exclude_keywords` in `community.json`. The installer for public Telegram news defaults to the chosen world name, so a channel for x1000 will not automatically receive x100-only posts. Matching is simple Unicode-aware keyword/phrase matching, not AI semantic classification or translation. Multiple world subscriptions sharing one feed URL reuse the same fetch. Details: [source filtering](docs/SOURCES.md).

## L2Dex castle tracking (opt-in)

The new community runner can also monitor the public **L2Dex New-Interlude x25** castle table. It compares ownership and newly registered attacker clans, then sends only changes after an initial silent baseline. It does not claim live combat or convert the site's unverified local siege time into UTC. The source is **disabled by default** in `community.example.json`. The live page layout was checked against nine castles, but a real ownership change has not yet been observed by the adapter; see [L2Dex integration notes](docs/L2DEX.md).

## Manually configured clan reminders (opt-in)

The Community Bot can also send event reminders without scraping or a VPS. Add explicit `scheduled_events` (start time with UTC offset, reminder lead times, destination subscription). Examples include clan meetings or **manual** raid boss timer estimates. These are not verified game events. The example reminder is disabled by default. See [reminder setup](docs/REMINDERS.md).

## Code map

- `github_runner.py`: current GitHub Actions runner; siege/news processing and Telegram moderation.
- `wiki_patch_notes.py`: Wiki article adapter and pending-news state integration.
- `messages.py`: Ukrainian text templates.
- `card_builder.py`: optional illustrated notifications.
- `fortress_bot.py`: legacy standalone runtime kept for reference/compatibility.
- `ops/dispatch_news_watchdog.sh` and `ops/systemd/`: legacy VPS dispatch/watchdog.
- `.github/workflows/news-bot.yml`, `.github/workflows/siege-bot.yml`: production jobs.
- `.github/workflows/ci.yml`: offline code regression tests for pull requests.
- `site_state.json`: **currently public, versioned state**; migration is planned. Do not add personal or private data.

## Development

```bash
python -m pip install -r requirements-actions.txt
TG_TOKEN=test TG_CHAT=test TG_CHAT_DEBUG=test python -m unittest -v \
  test_dispatch_watchdog test_fortress_loss_signal test_pending_news_queue \
  test_wiki_patch_notes test_workflow_contract
```

Offline tests do not need a Chromium browser download. To run the actual monitoring on a compatible machine, install the browser with `python -m playwright install chromium`. The old CentOS 7 server is incompatible with the Playwright driver used by this project.

## Contributing, roadmap and safety

Implementation tasks and acceptance gates: [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md). Coding agents should read [AGENTS.md](AGENTS.md) first. See [SECURITY.md](SECURITY.md) before sharing logs, secrets or custom news sources.

Code is published under the [MIT license](LICENSE). Third-party dependencies and media retain their own licenses.
