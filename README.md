# Scryde Fortress Bot

A Python Telegram bot for the **BSOE clan on Scryde Lineage 2 x1000**. It monitors fortress and castle sieges and publishes relevant Ukrainian-language server news.

**Now:** Scryde x1000 + Telegram. **Planned:** configurable Lineage 2 servers, community feeds, multiple destinations and Discord. See [the implementation plan](docs/IMPLEMENTATION_PLAN.md) for agent-ready milestones and honest status.

## What it does

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
| GitHub-only | Experimental opt-in | No | GitHub Actions cron; can be delayed |
| Existing VPS dispatcher | Active BSOE deployment | Yes, only for dispatch/watchdog | External `workflow_dispatch` every ~10 min |

The repository uses **two** workflows: [News Bot](.github/workflows/news-bot.yml) and [Siege Bot](.github/workflows/siege-bot.yml). Both can be run manually from GitHub Actions. The optional GitHub-only schedule is disabled by default and enabled with the repository variable `GITHUB_ONLY_MODE=true`. On forks/template repositories, event state is initialized as `community_state.json` to avoid inheriting BSOE alert history. Do **not** enable that variable for the existing VPS dispatcher unless the scheduling paths are coordinated.

See [GitHub-first deployment notes](docs/GITHUB_FIRST.md) for a test setup, required secrets, current limitations and offline checks. New template/fork deployments create a separate `community_state.json` instead of using the original BSOE history. A fully validated end-to-end onboarding flow is still an open milestone.

## Required repository secrets

- `TG_TOKEN`: Telegram bot token.
- `TG_CHAT`: destination chat ID.
- `TG_CHAT_DEBUG`: moderation/debug chat ID.
- `GEMINI_API_KEY`: Gemini API credential used for news filtering and rewriting.

Secrets belong in GitHub Settings → Secrets and variables → Actions. Do not put them in `config.py`, `site_state.json`, workflow YAML or issue comments. Existing default world/clan settings currently live in the workflows and environment variables. See [configuration details](docs/GITHUB_FIRST.md).

The news rewrite allows only specific Gemini model IDs in the current runner, but **zero billing also requires a Google AI Free Tier project with billing disabled**. Model allowlisting alone cannot guarantee zero charges.

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

## Configurable community library (under development)

The `community/` package can now parse a versioned [example configuration](community.example.json), read public RSS/Atom, Telegram pages, JSON and selected HTML, and format outbound Telegram or Discord webhook messages. All credential references are environment-variable names. The library now has an **opt-in Community Bot workflow** for public feeds and Telegram/Discord webhooks (20-minute best-effort schedule). It does not replace live Scryde siege monitoring. Configure it from [community.example.json](community.example.json), keeping all credentials in GitHub Secrets. First runs warm-start to avoid a flood of historical posts. See [GitHub-first setup](docs/GITHUB_FIRST.md). Documentation: [source and destination design](docs/SOURCES.md).

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
