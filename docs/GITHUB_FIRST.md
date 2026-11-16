# Deployment modes and configuration

## Current production behavior
The repository currently contains two independently dispatched GitHub Actions workflows: `news-bot.yml` and `siege-bot.yml`. A separate VPS systemd dispatcher runs them approximately every 10 minutes. Both workflows modify the tracked `site_state.json` and use the same GitHub Actions concurrency group `scryde-state`.

**New:** opt-in GitHub-only cron schedules are available, but they are *best effort*, not guaranteed exact 10-minute checks. A fresh template setup is **not yet validated** and the repository is not yet advertised as a one-click install. Consult `docs/IMPLEMENTATION_PLAN.md`.

## GitHub-only pilot (existing Scryde x1000 configuration)
1. Create a separate test repository from this source or fork it; enable GitHub Actions. Scheduled events execute from the default branch.
2. In repository Settings → Secrets and variables → Actions, add repository **secrets**: `TG_TOKEN`, `TG_CHAT`, `TG_CHAT_DEBUG`, `GEMINI_API_KEY`. `TG_CHAT_DEBUG` is for moderation/debug messages; restrict access.
3. Add a repository **variable** named `GITHUB_ONLY_MODE` with the exact value `true`.
4. Check that the bot has permission to post to the target Telegram channel/group; use a dedicated test channel first.
5. Run `News Bot` and `Siege Bot` once manually via Actions → workflow → Run workflow. Inspect logs, moderator previews, published messages and persisted state.
6. Monitor several scheduled cycles and verify no duplicated notifications. Remove/disable the variable to stop scheduled jobs.

**Important:** Do **not** enable `GITHUB_ONLY_MODE=true` in the existing BSOE repository until the VPS dispatcher has been stopped or deliberately coordinated. The manual `workflow_dispatch` route remains enabled regardless of this variable, so the watchdog continues to function.

## Runtime configuration today
| Name | Kind | Purpose |
| --- | --- | --- |
| `TG_TOKEN` | secret | Telegram Bot API token |
| `TG_CHAT` | secret | Production destination |
| `TG_CHAT_DEBUG` | secret | Moderation/debug destination |
| `GEMINI_API_KEY` | secret | AI news processing (requires a free-tier project without billing for zero billing) |
| `GITHUB_ONLY_MODE` | repository variable | Exact string `true` enables cron jobs |
| `OUR_CLAN` | workflow env | Clan to monitor, currently BSOE |
| `FORTRESS_URL`, `CASTLE_URL` | workflow env | Scryde x1000 ranking pages |
| `SCRYDE_CHANNEL_URL`, `SCRYDE_WIKI_UPDATES_URL` | workflow env | News sources |
| `NEWS_TARGET_CHAT`, `NEWS_APPROVE_DELAY_MIN` | workflow env | News moderation/delivery controls |
| `STATE_FILE` | workflow env | Serialized state path |

The current workflows still hardcode most nonsecret values. Configurable server/world/community setup belongs to P1 and is **not implemented yet**.

## Operational limitations
- GitHub scheduled runs may start late; inactive repositories can lose scheduled triggers. Treat critical siege notifications as best effort.
- Each fresh GitHub-hosted runner installs Python packages and Playwright Chromium. This can be slow and uses Actions minutes.
- `site_state.json` is currently versioned in Git, causing state commits. Keep it until a tested migration exists.
- Interactive Discord slash commands are not available in GitHub-only mode today.
- The repository currently monitors one clan on Scryde x1000 and publishes to Telegram; multi-server support is planned.

## Optional VPS mode
The existing VPS can continue to dispatch `workflow_dispatch` every 10 minutes with watchdog/recovery. It is *not* required for the experimental GitHub-only cron path. Additional real-time adapters or interactive Discord features may require an optional always-on process in a later milestone.

## Offline verification
```bash
python -m pip install -r requirements-actions.txt
TG_TOKEN=test TG_CHAT=test TG_CHAT_DEBUG=test python -m unittest -v \
  test_dispatch_watchdog test_fortress_loss_signal test_pending_news_queue \
  test_wiki_patch_notes test_workflow_contract
```
No live Telegram messages, browser downloads or API calls should occur in these offline tests.
