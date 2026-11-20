# Deployment modes and configuration

## Current production behavior
The repository currently contains two independently dispatched GitHub Actions workflows: `news-bot.yml` and `siege-bot.yml`. A separate VPS systemd dispatcher runs them approximately every 10 minutes. Both workflows modify the tracked `site_state.json` and use the same GitHub Actions concurrency group `scryde-state`.

**New:** opt-in GitHub-only cron schedules are available, but they are *best effort*, not guaranteed exact 10-minute checks. A fresh template setup is **not yet validated** and the repository is not yet advertised as a one-click install. Consult `docs/IMPLEMENTATION_PLAN.md`.

## GitHub-only pilot (existing Scryde x1000 configuration)
1. Create a repository using **Use this template** (or a fork) and enable GitHub Actions. Scheduled events run from the default branch. The original owner's `site_state.json` is deliberately ignored in other repositories: a fresh `community_state.json` is generated and committed there.
2. In repository Settings → Secrets and variables → Actions, add repository **secrets**: `TG_TOKEN`, `TG_CHAT`, `TG_CHAT_DEBUG`, `GEMINI_API_KEY`. `TG_CHAT_DEBUG` is for moderation/debug messages; restrict access.
3. Add a repository **variable** named `RUN_GITHUB_SCHEDULE` with the exact value `true`.
4. Optionally set GitHub Actions **variables** `OUR_CLAN`, `FORTRESS_URL`, `CASTLE_URL` and `SCRYDE_CHANNEL_URL` to suit your Scryde world. These URLs must actually provide the expected Scryde ranking format; other L2 networks are not supported by the legacy parser yet. Check that the bot can post to a dedicated test Telegram channel.
5. Run `News Bot` and `Siege Bot` once manually via Actions → workflow → Run workflow. Inspect logs, moderator previews, published messages and the new `community_state.json` state file.
6. Monitor scheduled cycles and verify no duplicated notifications. Remove/disable the variable to stop scheduled jobs. The expected update interval is best effort, not a promise; forks/private repos may have Actions minutes/storage quotas.

**Important:** Do **not** enable `RUN_GITHUB_SCHEDULE=true` in the existing BSOE repository until the VPS dispatcher has been stopped or deliberately coordinated. The manual `workflow_dispatch` route remains enabled regardless of this variable, so the watchdog continues to function.

## Runtime configuration today
| Name | Kind | Purpose |
| --- | --- | --- |
| `TG_TOKEN` | secret | Telegram Bot API token |
| `TG_CHAT` | secret | Production destination |
| `TG_CHAT_DEBUG` | secret | Moderation/debug destination |
| `GEMINI_API_KEY` | secret | AI news processing (requires a free-tier project without billing for zero billing) |
| `RUN_GITHUB_SCHEDULE` | repository variable | Exact string `true` enables cron jobs |
| `OUR_CLAN` | workflow env | Clan to monitor, currently BSOE |
| `FORTRESS_URL`, `CASTLE_URL` | workflow env | Scryde x1000 ranking pages |
| `SCRYDE_CHANNEL_URL`, `SCRYDE_WIKI_UPDATES_URL` | workflow env | News sources |
| `NEWS_TARGET_CHAT`, `NEWS_APPROVE_DELAY_MIN` | workflow env | News moderation/delivery controls |
| `STATE_FILE` | job env | `site_state.json` on the original BSOE repository; `community_state.json` on forks/templates |

The current workflows still hardcode most nonsecret values. Configurable server/world/community setup belongs to P1 and is **not implemented yet**.

## Operational limitations
- GitHub scheduled runs may start late; inactive repositories can lose scheduled triggers. Treat critical siege notifications as best effort.
- Each fresh GitHub-hosted runner installs Python packages and Playwright Chromium. This can be slow and uses Actions minutes.
- `site_state.json` is currently versioned in the original repository and will be included when you use a template. It is **not used** by fork/template workflows; their independently generated `community_state.json` still causes Git commits. Do not delete the original state in production.
- Interactive Discord slash commands are not available in GitHub-only mode today.
- The repository currently monitors one clan on Scryde x1000 and publishes to Telegram; multi-server support is planned.

## Optional VPS mode
The existing VPS can continue to dispatch `workflow_dispatch` every 10 minutes with watchdog/recovery. It is *not* required for the experimental GitHub-only cron path. Additional real-time adapters or interactive Discord features may require an optional always-on process in a later milestone.

## Offline verification
```bash
python -m pip install -r requirements-actions.txt
TG_TOKEN=test TG_CHAT=test TG_CHAT_DEBUG=test python -m unittest -v \
  test_dispatch_watchdog test_fortress_loss_signal test_pending_news_queue \
  test_wiki_patch_notes test_workflow_contract test_p0_hardening test_state_persistence
```
No live Telegram messages, browser downloads or API calls should occur in these offline tests.


## New multi-community news mode (experimental, fully GitHub-hosted)

For the new stateless public feed pipeline, copy `community.example.json` to `community.json` in your own repository and customize:
- source network, world, chronicle, URL and explicit enabled flag;
- Telegram/Discord destination aliases, pointing only to environment variable names;
- subscriptions by destination/world/source/type/clan.

The sample Scryde Telegram source is **disabled** because it may include posts for worlds besides x1000. Enable a source only after checking that its content is appropriate for your community. The new runner does not yet AI-filter or translate cross-world official news.

Set repository variables `COMMUNITY_MODE=true` and `RUN_GITHUB_SCHEDULE=true`. Optionally set `COMMUNITY_DRY_RUN=true` to inspect a run without delivery or state mutations. Keep `TG_CHAT` and `TG_TOKEN` as secrets, or store a flat JSON mapping of environment variable names to secret values in `COMMUNITY_SECRETS_JSON` (GitHub **Secret**, not a checked-in file) for multiple targets. Set `COMMUNITY_DRY_RUN=false` only after verifying authorized destination permissions.

Select Actions → Community Bot (GitHub-only) → Run workflow to trigger once. Scheduled checks are requested at minute 3, 23 and 43 of each hour (UTC), but GitHub can delay or skip them. The first successful feed snapshot only warms subscriptions; subsequent new posts are eligible for delivery. Delivery IDs are stored as hashes in public `community_deliveries.json`, which is committed to Git by the workflow, while real chat/webhook values remain in secrets. GitHub-only output works for Discord **webhooks** but not always-on slash commands.

The old News Bot and Siege Bot workflows are skipped when `COMMUNITY_MODE=true` so no duplicate legacy Scryde polling occurs. The new public feed runner **does not yet reproduce Scryde live siege alerts**. To run the original Scryde tracker, leave `COMMUNITY_MODE` unset/false.

This feature is new and not yet end-to-end verified with a user's real Telegram/Discord credentials. Do not assume reliable delivery until a test channel and repeated runs have passed.



## One-time GitHub Actions setup (new installation, no command line)

A fresh fork/template copy can run **Actions → Set up Community Bot (one-time) → Run workflow**. Choose its public game network, world, chronicle, source URL, source type and Telegram/Discord output. The workflow validates them and commits a new `community.json` containing only public source metadata and **names of secret environment variables**. It refuses to overwrite an existing `community.json` or run in the original Spellhow/BSOE repository.

After configuration, set the following in your own repository:

1. Telegram: Actions secrets `TG_TOKEN` and `TG_CHAT`, or Discord: Actions secret `DISCORD_WEBHOOK`. For several destinations, use `COMMUNITY_SECRETS_JSON` with a flat mapping from environment names to secret values (never commit it to Git).
2. Actions repository variables `COMMUNITY_MODE=true` and `RUN_GITHUB_SCHEDULE=true`.
3. Use `COMMUNITY_DRY_RUN=true` initially to check source accessibility without sending or saving alerts. Turn dry-run off for the first baseline, which intentionally sends no historical source events.
4. Run **Actions → Community Bot (GitHub-only)** once, verify its logs, and check that state is persisted to `community_deliveries.json`. Scheduled checks thereafter are best-effort.

The setup workflow does not request or handle actual Telegram chat IDs, bot tokens or Discord webhook secrets. It is intentionally one-time to avoid overwriting customized subscriptions.

If you prefer a local shell, run `python scripts/setup_community.py --help`. Neither setup path needs a VPS, Docker or browser.



### Clean archive/fork portability

The legacy root `config.py`, `state.json` and `test.py` files remain ignored, while reusable modules such as `community/config.py` must be committed to new repositories. Scoped ignore rules and `test_template_gitignore.py` prevent Git archive / fresh Git init copies from accidentally omitting the new community configuration parser.



## GitHub Actions variable naming

The exact schedule toggle is `RUN_GITHUB_SCHEDULE=true`. GitHub **rejects repository variable names beginning with `GITHUB_`**, so `GITHUB_ONLY_MODE` is an obsolete name from early iterations and must not be used. This was verified during the first clean GitHub Actions smoke test on 2026-11-17.



## Verified private-repository onboarding test (2026-11-17)

A temporary private repository constructed from a clean Git archive passed the following GitHub Actions checks:

- One-time setup successfully committed `community.json` without secrets.
- Community Bot dry-run read the public L2Dex source: `sources=1`, `errors=0`, no messages sent.
- The first normal baseline committed `community_deliveries.json` with no outgoing message.
- GitHub accepted the correctly named repository variable `RUN_GITHUB_SCHEDULE`.

The test found and resolved two blockers: incorrectly scoped ignore rules for `community/config.py` (PR #12), and the invalid `GITHUB_ONLY_MODE` variable prefix (PR #13). The main repository is now marked as a GitHub template.

**Still pending:** real new-event delivery to an authorized Telegram/Discord destination, a recurring cron-cycle check and fully independent-account onboarding. The private test repository was archived instead of deleted because the available GitHub OAuth grant lacks `delete_repo` scope.



## Avoid cross-world news in the Community Bot

The one-time GitHub Actions setup includes an optional comma-separated **include_keywords** field for public sources. For a Scryde public Telegram source and world `x1000`, leaving this blank safely defaults to `["x1000"]` so x100-only news is not accidentally delivered. A post about all worlds that does not actually mention x1000 will be skipped; users can broaden the criteria by editing `community.json` afterward. Other feed types remain unfiltered unless keywords are explicitly provided.

The feature is a deterministic Unicode keyword filter, **not Gemini/AI translation or classification**. The new Community Bot does not automatically translate a message when a subscription requests another language. A future optional review/AI step remains on the roadmap.



## Changing source URLs safely

The Community Bot automatically treats an edited source URL or parser selector as a new public feed. Its first successful observation only records the existing entries; it does not dump the new source's entire history into Telegram or Discord. Newly published events after that baseline are eligible for alerts. For L2Dex, the ranking URL is also part of the tracked castle snapshot identity, preventing a new ranking page from creating fictional castle ownership transitions.



## Verify Telegram or Discord delivery before enabling cron

After creating `community.json` and configuring GitHub Secrets, set the repository variable `COMMUNITY_MODE=true` and keep `RUN_GITHUB_SCHEDULE` unset until a real test succeeds.

Open **Actions → Test Community Delivery (manual)**, provide the exact destination alias from `community.json` (for example `clan-channel`) and deliberately check **Send exactly one test message?**. The job sends one clearly labeled manual diagnostic and requires a real Telegram/Discord message ID. It never fetches game data, changes state or publishes news. It is blocked in `Spellhow/scryde-fortress-bot` and cannot run on a schedule.

If permissions or secrets are missing, the run fails without printing a token, chat ID or webhook URL. Repeat the test only after correcting credentials and explicitly confirming again. Once your authorized channel receives the message, turn on `RUN_GITHUB_SCHEDULE=true` to enable regular best-effort polling.

This creates a self-service test workflow; **the maintainer has not yet performed live delivery testing with an authorized external channel**.



## Source preview and request limits

Before enabling a new public source for delivery, run **Actions → Preview Community Sources (manual)** in your own repository with `COMMUNITY_MODE=true`. Choose a source alias or leave it blank to preview up to five enabled feeds. It validates the source/parser and existing keyword filters without Telegram/Discord credentials, without sending messages, and without modifying state.

For politeness and GitHub Actions cost control, a single Community Bot run fetches no more than six distinct public URLs from any one domain. Shared URLs are fetched once regardless of how many worlds or destinations subscribe. Extra sources are reported as deferred; reduce or spread out source URLs rather than raising the limit arbitrarily.



## If public sources temporarily fail

The Community Bot automatically retries a failed public HTTPS source with persistent bounded backoff: 20, 40, 80, then at most 120 minutes. Its health markers contain only hashed URL identifiers and numeric retry times in `community_deliveries.json`. This works in GitHub-only mode with no additional database.

The Actions summary now includes `deferred_sources`. A deferred source is not interpreted as a game event, nor as a fresh failed network request. For a voluntary immediate check that does not alter state, set `COMMUNITY_DRY_RUN=true` and run the Community Bot manually, or use the dedicated source-preview workflow.


## Community state concurrency and rollback

The GitHub-only Community Bot now uses `ops/persist_community_state.sh` instead of the legacy `ops/persist_state_with_retry.sh`. It compares the state at workflow start with the latest remote commit: independently confirmed delivery hashes are unioned and unrelated cursor updates retained. If both sides changed the same castle/source cursor incompatibly, persistence **fails closed** instead of overwriting an observation.

The only staged commit file is `community_deliveries.json`. Original BSOE `site_state.json` and its persistence script are untouched. Offline tests with competing Git clones cover remote advances, untouched configuration, fresh template state and conflicting cursors. This is not a mathematical exactly-once delivery guarantee: a crash after remote acceptance but before persistence can still produce a duplicate.

Rollback: revert the Community Bot persistence workflow change. This does not alter the state schema, but returning to the old script loses the new conflict-resolution safeguards.


## Multi-channel delivery safety

For multiple Telegram/Discord destinations, use distinct, stable aliases such as `clan-uk` and `clan-en`; aliases are case-insensitive for delivery receipts. Aliases differing only by case (for example `Clan` and `clan`), or with leading/trailing whitespace, are now rejected to prevent accidentally sharing one receipt across two different channels.

One destination can have multiple subscriptions. When overlapping rules select the **same event**, the sender attempts that event only once per run even if the first attempt fails. It can retry on the next run after a failure. Overlapping subscriptions requesting **different languages for one destination and event** are rejected at configuration validation, rather than silently publishing whichever language happens to appear first in JSON.

Different destinations remain independent: failure in one does not block the others. Up to 100 subscription rules are accepted per `community.json`. This is configuration hygiene and offline transport isolation, **not a real Telegram administrator-permission verification**.


## Automatic parser-failure cooldown

The Community Bot distinguishes **HTTP failures** from **parser failures**.
An inaccessible public URL receives the existing shared per-URL
exponential cooldown. A successfully fetched but malformed RSS, JSON,
forum HTML, or castle table now receives its own **parser-specific** retry
delay of 20, then 40, then 80, up to 120 minutes, persisted in the ordinary
GitHub-only JSON state. A different healthy source using the **same public URL**
still processes normally.

The parser cooldown key is a hash of the source alias, world, kind, URL,
selector and keyword filters. It does **not** expose response content,
tokens or source addresses in public state. Editing the relevant parser
configuration starts a fresh retry identity. A successful parse clears its
cooldown; dry runs and source previews never mutate these markers.

These delays are **only source retry throttles**, not a promise about
GitHub Actions cron accuracy or the availability of a site. Other sources,
destinations, and scheduled/manual reminders continue running.


## Add a second Telegram or Discord destination

The one-time setup workflow creates **one destination**. To add another without
hand-editing multiple JSON sections, run this locally or in a trusted checkout:

```bash
python3 scripts/add_community_destination.py \
  --config community.json \
  --source-id initial-source \
  --alias second-discord \
  --kind discord \
  --address-env DISCORD_WEBHOOK_SECOND \
  --language en \
  --output community.updated.json
```

The command copies your original config and creates **one additional isolated
destination and a source-scoped subscription**. It validates the resulting
complete config before writing. It refuses to overwrite `community.json` or an
existing output file. No network, token read, or live send is performed.

For another Telegram channel, use `--kind telegram --address-env TG_SECOND_CHAT`
and optionally `--token-env TG_SECOND_BOT_TOKEN`. If you omit `--token-env` for
Telegram, the new destination **shares** the existing `TG_TOKEN`. For Discord,
the token is embedded in the secret webhook URL referenced by `--address-env`;
never paste the webhook URL itself into an argument or JSON file.

Use `--event-types news,announcement` to select supported event categories
from the chosen source, or use `--clans YourClan` **only for L2Dex castle
sources**, where the clan field currently represents the observed owner,
**not** the registered attacking clan. By default the new subscription receives
all event categories supported by that source. Language is routing metadata:
the current lightweight Community Bot does **not** automatically translate
source texts, even if `--language en` or `--language uk` is selected.

After reviewing `community.updated.json`, put the **actual secret values**
in repository Settings → Secrets and variables → Actions (for multiple target
secrets, use the existing `COMMUNITY_SECRETS_JSON` secret mapping). Replace
`community.json` with the reviewed candidate and commit the configuration
with **only env-var names**. Keep scheduled delivery disabled, run validation,
dry-run the source, then use **Actions → Test Community Delivery (manual)** on
each destination with explicit authorization. Only enable the schedule after
confirming the messages arrive.

These tests cover two destinations, one fetch per source per run, independent
receipts, different subscription languages and failed-target retry. Live
multi-channel permission checks remain a separate verification step.


## State write churn and GitHub Actions logs

GitHub-only Community Bot stores hashed delivery acknowledgements and public
source cursors in `community_deliveries.json`. It now writes the canonical,
sorted JSON **only when the actual content differs**. A successful unchanged
run will not create another temporary file, rewrite the state, or change its
filesystem modification time. Changed content still uses a temporary file,
an explicit file flush and filesystem sync, followed by atomic replacement.
A simulated replacement failure leaves the previous state intact.

The runner's summary now includes `state_changed=yes` or `state_changed=no`.
The existing Git state-persistence step separately checks for an unchanged
file and skips Git commits when there is no new state. Inspect the logs for
these markers when estimating Git history churn and Actions overhead.

A successful send that occurs just before a process crash *can still be
delivered twice* if the receipt was not persisted to GitHub in time. The
new no-op write optimization does **not** claim cross-process exactly-once
delivery or solve that fundamental external acknowledgement window.


## Credential preflight before live delivery

`python3 community_runner.py --validate` verifies the JSON configuration
without loading secrets. After setting repository Secrets, run
`python3 community_runner.py --check-credentials` in an authorized
environment with the Secrets injected. It performs **no fetches or sends**
and does not write state. It reports only the count of active subscribed
destinations and the names of missing/invalid secret *environment variables*,
not token values, chat IDs or webhook URLs.

The Community Bot workflow now performs this check before polling when
`COMMUNITY_DRY_RUN` is not `true`. If one destination is missing a secret,
the preflight is reported as degraded, **but does not block healthy
destinations** from sending: source polling continues, successful receipts
are persisted, and the overall job reports failure for investigation.
Disabled-only/unsubscribed destinations are not required to provide secrets.

The check recognizes ordinary GitHub Secrets and the existing flat JSON
`COMMUNITY_SECRETS_JSON` mapping for multiple channels. It checks presence
and the structural shape of Discord webhook URLs; **it cannot verify bot
membership, Telegram chat permissions, Discord webhook revocation, or actual
API acceptance**. For those, use the separately authorized manual
`Test Community Delivery` workflow with one test message per destination.
A dry-run mode remains possible without any Secrets.
