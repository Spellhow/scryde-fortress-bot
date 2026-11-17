# Agent instructions

Read `docs/IMPLEMENTATION_PLAN.md` before starting feature work. The user has chosen **GitHub-first** deployment; optional VPS/self-hosted operation must never become a requirement for a basic installation.

## Working rules
- Do not edit `site_state.json` during refactors or tests. It is currently tracked production state. Migration belongs to milestone P1-STATE and requires a rollback plan.
- Do not commit bot tokens, API keys, chat identifiers from private deployments, browser cookies, credentials, debug dumps or personal messages.
- Existing BSOE / Scryde x1000 outputs must remain compatible until the migration has passed regression and side-by-side checks.
- Work in small, reviewable PRs, with a test and explicit acceptance criteria for every behavior change. No broad rename or all-at-once rewrite.
- Prefer GitHub Actions, environment/repository variables and a simple documented configuration. Avoid required Docker, VPS, PostgreSQL, website dashboards or hosted SaaS for the starter setup.
- Scrape public sources only where permitted. Respect rate limits, robots/terms where applicable, avoid bypassing access controls and never fetch private Telegram/Discord content without authorization.
- Never assume a server provides live attack or boss data. Distinguish observed events from timetable estimates and manually entered timers.
- Keep local CI offline: no live site access, no real Telegram/Discord messages, no Gemini calls.
- Check the status of both existing `news-bot.yml` and `siege-bot.yml` before touching deployment. They share `site_state.json` and the `scryde-state` concurrency group.
- Do not enable `RUN_GITHUB_SCHEDULE` in the owner repository while the VPS dispatcher is active. The fallback scheduler is opt-in.
- Avoid adding full browsers or a build step to PR validation. Workflow minutes and Git write volume are constraints.

## For each implementation task
1. Confirm the corresponding milestone and dependencies in `docs/IMPLEMENTATION_PLAN.md`.
2. Write down the existing observable behavior (fixtures/tests) before refactoring.
3. Implement the smallest vertical slice with feature flags or compatibility adapters.
4. Run targeted offline tests; inspect output, not just exit code. Verify GitHub-only mode and current VPS mode.
5. Update README/configuration docs, tests and the milestone checkbox only when acceptance criteria are actually met.
6. In the PR description, state regression risk, data migration needs, manual checks and rollback instructions.

## Commands
```bash
TG_TOKEN=test TG_CHAT=test TG_CHAT_DEBUG=test python -m unittest -v \
  test_dispatch_watchdog test_fortress_loss_signal test_pending_news_queue \
  test_wiki_patch_notes test_workflow_contract test_p0_hardening test_state_persistence test_community_core test_community_sources test_community_runner test_l2dex_adapter test_community_schedules test_setup_community test_template_gitignore test_scryde_shadow test_scryde_fail_closed test_community_relevance test_transport_delivery test_github_runner_text test_delivery_probe test_source_preview test_source_health test_scryde_shared_rows test_community_state_merge test_scryde_decision_parity test_subscription_isolation test_legacy_state_preflight test_discord_embeds
python -m compileall -q github_runner.py fortress_bot.py wiki_patch_notes.py messages.py card_builder.py
```
These tests require packages in `requirements-actions.txt` but do **not** require installing the Chromium browser. Use real secrets only in the protected runtime workflows.
