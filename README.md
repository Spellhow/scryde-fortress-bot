# Scryde Fortress Bot

Telegram bot for clan `BSOE` that monitors Scryde fortresses and castles and sends alerts about:

- attacks on our fortress or castle
- our clan attacks on enemy objects
- cancelled sieges
- lost ownership

The original CentOS 7 deployment is kept for reference, but the active deployment target for this repository is **GitHub Actions** with **Playwright**.

## Why GitHub Actions

The target site now uses JS anti-bot protection, so plain `requests` is no longer enough.
GitHub Actions provides a fresh Ubuntu runner where Playwright works reliably without touching the production server that also hosts other projects.

## Repository secrets

Configure these repository secrets before enabling the workflow:

- `TG_TOKEN`
- `TG_CHAT`
- `TG_CHAT_DEBUG`
- `GEMINI_API_KEY`

## Workflow behavior

- Runs every 15 minutes
- Uses Playwright Chromium to load:
  - `https://ua.scryde.game/rankings/1000/fortresses`
  - `https://ua.scryde.game/rankings/1000/castles`
- Fetches `https://t.me/s/scryde` and rewrites only `x1000`-relevant news through Gemini
- Blocks heavy asset types like images, fonts, media, and stylesheets
- Stores bot state in `site_state.json`
- Commits updated `site_state.json` back to the repository automatically
- Applies a 60-minute backoff if the site returns anti-bot challenge without usable data

## Main files

- `.github/workflows/fortress-bot.yml` — scheduled GitHub Actions workflow
- `github_runner.py` — Playwright-based runner for GitHub Actions
- `messages.py` — notification templates
- `card_builder.py` — optional Telegram image card generator
- `site_state.json` — persisted state between workflow runs

## Local dry run

Use this only on a machine where Playwright works:

```bash
pip install -r requirements-actions.txt
python -m playwright install chromium
```

Set env vars:

```bash
TG_TOKEN=...
TG_CHAT=...
TG_CHAT_DEBUG=...
python github_runner.py
```

## Notes

- `config.py` is intentionally excluded from git because it contains server-local secrets.
- The old CentOS 7 server is not used for browser automation because Playwright crashes there.
