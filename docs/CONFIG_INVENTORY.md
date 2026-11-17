# Configuration inventory and compatibility (P0)

This inventory covers the present single-clan Scryde runtime. New multi-world/community configuration is tracked in the implementation plan and does not exist yet.

## GitHub Actions controls

| Scope | Variable / secret | Source now | Default/current behavior | Notes |
| --- | --- | --- | --- | --- |
| Repository variable | `RUN_GITHUB_SCHEDULE` | GitHub Actions | unset (cron jobs skipped) | Keep unset if the VPS watchdog dispatches jobs |
| Repository variable | `OUR_CLAN` | GitHub Actions | `BSOE` | Injected into siege and news jobs; no changes for owner |
| Repository variable | `FORTRESS_URL` | GitHub Actions | Scryde x1000 fortress ranking | Must stay on the intended game world |
| Repository variable | `CASTLE_URL` | GitHub Actions | Scryde x1000 castle ranking | Validate public URL before editing |
| Repository variable | `SCRYDE_CHANNEL_URL` | GitHub Actions | `https://t.me/s/scryde` | Public news only |
| Secret | `TG_TOKEN` | GitHub Actions | required | Never log |
| Secret | `TG_CHAT` | GitHub Actions | required | The destination is not yet configurable per community |
| Secret | `TG_CHAT_DEBUG` | GitHub Actions | recommended | Moderation/debug |
| Secret | `GEMINI_API_KEY` | GitHub Actions | required for AI news | Free-tier project with billing disabled is necessary for zero billing |

Other workflow environment settings are fixed on purpose for backward-compatible BSOE production: `RUN_NEWS`, `RUN_NEWS_QUEUE`, `RUN_SIEGES`, `NEWS_TARGET_CHAT`, `NEWS_APPROVE_DELAY_MIN`, `NEWS_PENDING_EXPIRE_HOURS`, `NEWS_AUTO_PUBLISH_GRACE_MIN`, `NEWS_MAX_NEW_POSTS_PER_RUN`, `STATE_FILE`, retry/backoff, Wiki URL and supported Gemini model IDs.

## Code configuration

- `github_runner.py`: environment variables for Telegram credentials, Gemini, source URLs, clan, state, moderating queue, Playwright retry policy, and health diagnostics. Top-level initialization currently requires `TG_TOKEN` and `TG_CHAT`.
- `wiki_patch_notes.py`: Wiki URL/model fallback, request/browser timeouts, HTTP retries and health notification cooldown.
- `fortress_bot.py`: legacy direct server runner, reads its historical `config.py` (untracked), and includes Telegram polling commands. Not the GitHub Actions production code path.
- `card_builder.py`: fixed card colors/fonts; image URL generation may depend on the ranking source.
- `site_state.json`: public tracked state, including the existing BSOE ownership and news queues. Do not delete/reset until a migration; new template users must initialize a fresh state separately.

## Next migration

Create a validated `network/world/chronicle/clan/sources/destinations` model without changing current defaults. Keep secrets in GitHub Actions secrets or an encrypted/authorized store. Per-destination user IDs and moderation queues must not be committed publicly.



## Legacy news moderation permissions

`TG_CHAT_DEBUG` is the only authorized chat for the legacy `news:*` callback buttons, `/news_*` commands and `+/-/delay` reply shortcuts. Empty or mismatched chat IDs fail closed. Both legacy News and Siege workflows may consume moderation callbacks; both receive the same optional Actions Secret `NEWS_ADMIN_USER_IDS`.

If `NEWS_ADMIN_USER_IDS` is a comma-separated list of decimal user IDs, only those users may issue moderation actions **inside the trusted chat**. Example format: `111111111,222222222` (illustrative IDs). Invalid or empty entries in a nonblank allowlist deny all moderation actions rather than opening access.

Without `NEWS_ADMIN_USER_IDS`, all members who can interact in the dedicated debug chat may moderate, as before. The recommended setup is a restricted debug chat plus a user allowlist. Store IDs as GitHub **Secrets**, never as literals in workflow YAML or in public state.
