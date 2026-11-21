# Community sources and destinations (P1 library)

Status: reusable parsers, public HTTPS client, configuration and outbound publishers are implemented; an opt-in GitHub-only workflow is present for new community feeds. Existing BSOE production is unchanged.

## Configuration

Copy community.example.json to a private/community-specific configuration file in your own repository when the runner becomes available. The public JSON lists source URLs, game network, world, chronicle, destination **aliases**, and environment variable references. Do not put real Telegram chat IDs, bot tokens or Discord webhook URLs in committed JSON.

Supported source kinds:
- rss: public RSS or Atom feed, news text and article links.
- telegram_public: public t.me/s/<channel> pages only; not Telegram private groups.
- scryde_forum: read-only public posts in the official Scryde updates thread on board.scryde.net. Stable numeric post IDs, no login. Requires explicit keywords to avoid broadcasting unrelated game worlds. Experimental opt-in; see limitations below.
- json_api: public JSON array or {"events":[...]} with id/title/body/url/kind.
- webpage: selected article/main HTML nodes; optional short CSS selector.
- l2dex_castles: dedicated L2Dex castle ranking parser for verified public ranking URLs. Tracks owner and attacker-registration **changes**, not live combat. [Integration details](L2DEX.md); disabled in the example.

Every source is scoped to a specific network and world. A subscription references an existing destination alias and the same game world; optional event_types, source_ids and clans restrict delivery.

The parser does not translate content by itself. A future AI/moderation layer will handle locale-specific output and prevent duplicate paid model calls.

## Network safety

The new client supports only HTTPS on port 443. It resolves all DNS answers and rejects non-global addresses, pins the public IP for the actual TLS connection (hostname verification remains enabled), refuses redirects, limits bodies to 512 KiB and enforces a short timeout. This does not authorize scraping websites that prohibit it. Polling frequency and source opt-in must respect provider terms.

## Outbound delivery

Telegram Bot API: destination uses address_env and token_env pointing to secret environment variables.
Discord: destination uses address_env pointing to an HTTPS discord.com/api/webhooks/... webhook secret. Webhook notifications are supported without an always-on host. Interactive slash commands will require a separate optional service.

The publisher sends plain source text (no HTML interpreted by Telegram), disables Discord role mentions, and returns success only for a confirmed response. Errors are sanitized to avoid printing tokens/webhooks. No delivery state stores a destination's real address.

## Operational status

The new public multi-community runner is available as an experimental opt-in workflow. Cross-world AI filtering, moderation, fresh real-credential smoke test, and Scryde-to-core production cutover remain open milestones. GitHub-only schedule is best effort.

## Manual schedules (no external source)

The optional `scheduled_events` configuration enables custom reminders without fetching a website. These events are labeled `manual` provenance and need an explicit timestamp with UTC offset, a stable ID, a game world, title, and one or more `remind_before_minutes`. Subscribe to `manual_schedule` and `event_reminder` for the matching world. See [details and examples](REMINDERS.md). GitHub Actions timing remains best-effort.



## Source world relevance without paid AI

Public game feeds may mix announcements about many game worlds. The new optional source configuration supports:

```json
{
  "id": "scryde-x1000-news",
  "kind": "telegram_public",
  "world": {"network": "Scryde", "name": "x1000"},
  "url": "https://t.me/s/scryde",
  "enabled": true,
  "include_keywords": ["x1000"],
  "exclude_keywords": ["x50"]
}
```

Here `include_keywords` means the title or body must contain **at least one** listed phrase; `exclude_keywords` takes precedence and suppresses a matching post. Case-folding is Unicode-aware and matches complete words/phrases, so `x100` will not match `x1000`. This is a conservative text filter, **not semantic AI classification**; it can miss posts not mentioning a world and cannot guarantee perfect relevance.

A new one-time GitHub setup for a **public Telegram source** defaults to requiring the configured world name, unless explicit comma-separated `include_keywords` are supplied. For RSS, HTML, JSON sources with no keyword settings, all public entries still pass through as in previous versions. Edit `community.json` to add explicit include/exclude filters to those sources too. L2Dex castle snapshots reject keyword filtering: use destination/subscription filters instead.

If two sources have the same URL but different worlds, the runner fetches that URL only **once per job**, normalizes it for each world and applies each source's keyword settings independently. Changing keyword settings warm-starts that subscription again (silent snapshot) rather than posting a backlog of old news. The legacy BSOE Gemini moderation flow is separate and unchanged.



## Preview configured sources safely

In your template-based repository, set `COMMUNITY_MODE=true`, then open **Actions → Preview Community Sources (manual)**. Leave the source alias blank to preview up to the first **five enabled** sources, or provide an existing source alias. This action is disabled on the original BSOE repository.

Previews apply the configured source filters and show only a short sanitized title (or L2Dex castle name/observed owner), item counts, and safe error categories. They **never** send Telegram/Discord messages, contact AI models, read secrets or change delivery state. Check the preview before enabling an unfamiliar feed or scheduled alerts.

Each Community Bot run limits fresh public HTTP requests to **six distinct URLs per domain**, including several source aliases sharing one domain. Identical URLs share a single fetch, even across game worlds. Over-budget URLs are deferred and reported as degraded rather than retried aggressively. This is an *in-run* limit; exponential backoff across runs and provider-specific limits are still future work.



## Retry and source health between GitHub runs

When a public HTTPS fetch fails, Community Bot stores only a hashed source URL key, the consecutive failure count and the next allowed retry time in `community_deliveries.json`. Subsequent scheduled runs **do not repeatedly hit the same failing URL** before its retry window.

The backoff follows `20 → 40 → 80 → 120 minutes` (maximum two hours). A successful public fetch clears the failure record. Multiple world subscriptions to the same URL share one backoff decision, preventing repeated paid/network work.

A skipped retry is reported as `deferred_sources` in the GitHub Actions log, not as a fresh transport failure. New HTTP failures still mark that run degraded. Manual `COMMUNITY_DRY_RUN=true` bypasses the cooldown to inspect a source without mutating backoff or delivery state.

This policy does not imply that a temporarily unavailable webpage means a castle has been lost or a siege cancelled. A source with invalid but successfully fetched HTML is still rejected by its parser; parser-specific cross-run backoff remains future work.


## Experimental Scryde forum source

To preview the existing public updates thread (not the legacy BSOE moderation queue), add a disabled source to a Community Bot configuration and select a verified current page:

```json
{
  "id": "scryde-forum-x1000",
  "kind": "scryde_forum",
  "world": {"network": "Scryde", "name": "x1000"},
  "url": "https://board.scryde.net/threads/obnovlenija.30694/page-18",
  "enabled": false,
  "include_keywords": ["x1000"],
  "exclude_keywords": ["x50"]
}
```

This example page number is a **verified public reference as of 2026-11-17**, not a permanent latest-page endpoint. Site page counts change; a page can redirect when removed/renumbered. The GitHub-only HTTP client deliberately refuses redirects for safety and therefore will not automatically follow the thread's latest-page redirect. Inspect the current public page and update the URL manually before enabling the source. The parser does not bypass CAPTCHA or authentication.

The adapter reads public XenForo article post IDs, normalizes them as stable `forum-post:<id>` identities and marks them as `observed`. Missing/malformed content, duplicate conflicting IDs and challenge/error HTML cannot generate synthetic events. Initial subscriber activation silently warms existing posts; subsequent visible new IDs can be sent independently to authorized Telegram/Discord destinations.

This forum mixes news about multiple servers. Explicit `include_keywords` is mandatory until verified semantic filtering is available. Matching one keyword is an **approximation**, and general updates applying to every server may be omitted. No Gemini adaptation, moderator approval, private forum access, live-source delivery smoke test, or mapping of legacy `forum_news` IDs is implemented yet. The existing BSOE News Bot continues on its original parser.



### Forum pagination and preserved history

For `scryde_forum`, changing the configured URL from one `page-N` to another inside the **same official thread** preserves the original subscription warm-start and delivery receipts. A source should not silently warm-start again and drop newly visible post numbers merely because the forum pagination advanced. Older handled IDs remain suppressed for the specific destination when a legacy forum migration marker has been installed.

Moving to a new page remains a **manual** GitHub-only configuration action. Redirected, inaccessible or challenge pages generate a source error rather than invented news.


## Forum page changes and existing warm-start state

The Scryde forum has one public thread split across numbered pages. Community Bot now uses the thread's stable identity for subscription warm-start state, so updating `page-18` to `page-19` in `community.json` does **not** silently warm-start and discard the newly visible posts.

An early Community Bot version stored a URL-specific `warm:...` marker. During normal operation, the runner now recognizes that previous marker **only when the current source URL, world, filters and destination still match** and its value is `initialized`. It promotes the marker to the canonical thread identity, preserving old receipt records and retaining the original marker for rollback.

For upgrades from the original forum adapter, first run the updated code **without changing the configured page URL**. After the first healthy poll has saved the canonical marker, change the URL to the newly verified public page. If both code and URL change together, the old marker cannot be safely recovered from a hashed key and the new source will instead follow conservative silent warm-start behavior. No AI call or live message is made by this migration.


## Forum page changes and existing warm-start state

The Scryde forum has one public thread split across numbered pages. Community Bot now uses the thread's stable identity for subscription warm-start state, so updating `page-18` to `page-19` in `community.json` does **not** silently warm-start and discard the newly visible posts.

An early Community Bot version stored a URL-specific `warm:...` marker. During normal operation, the runner now recognizes that previous marker **only when the current source URL, world, filters and destination still match** and its value is `initialized`. It promotes the marker to the canonical thread identity, preserving old receipt records and retaining the original marker for rollback.

For upgrades from the original forum adapter, first run the updated code **without changing the configured page URL**. After the first healthy poll has saved the canonical marker, change the URL to the newly verified public page. If both code and URL change together, the old marker cannot be safely recovered from a hashed key and the new source will instead follow conservative silent warm-start behavior. No AI call or live message is made by this migration.


## Detecting successful HTTP responses that are not actual feeds

A `200 OK` response does **not** establish that a configured page contains
public news. Some sites return CAPTCHA, login or generic error HTML with an
apparently successful HTTP status.

The public Telegram source now requires **at least one trustworthy post**
in the requested channel, with a positive bounded message ID. A post from
a different channel, an invalid ID, a duplicate ambiguous ID or media-only
record does not establish a valid news snapshot. Official source links are
derived from the validated channel and post ID; untrusted `href` values in
returned HTML cannot point a delivered event at another site.

RSS/Atom sources now require the expected XML root type. A well-formed
`<html>` challenge/error response is rejected rather than accepted as an
empty RSS feed. Truly empty but valid RSS/Atom feeds remain supported.
Generic webpage sources must match their configured selector (`article,
main` by default); no matching element is a parsing failure, not a
successful empty first-run baseline.

These failures use the GitHub-only source-specific parser backoff described
in [deployment notes](GITHUB_FIRST.md). The runner does **not** advance
subscription warm-start markers or acknowledge empty source data when it
cannot establish that a trustworthy feed was parsed. This check does not
guarantee detecting every possible antibot/error response; live preview
and regular review of chosen sources are still required.


## Public URLs shown in outbound messages

Untrusted RSS, JSON or HTML posts can include source URLs that differ from
the configured feed address. The Community Bot now uses one conservative
display-link rule for *both* Telegram and Discord. A public source link must
be HTTPS, reasonably short, free of credentials and obvious local/private
hosts, with no credential-like query parameters (such as `token`,
`access_token`, `api_key`, `session_id` or `client_secret`). Arbitrary URL
fragments are rejected; the official Scryde `#post-123` forum anchor is
preserved.

During feed normalization, entries with unsafe links are skipped rather
than advertising an untrusted endpoint. At the outbound boundary, the
message body can still be sent, but unsafe source URLs are omitted even if
an integration constructs an Event directly. Discord rich embeds and
ordinary Telegram/Discord texts now agree on this policy.

This is **display validation, not link fetching**. It cannot establish that
a remote HTTPS domain is honest or that its content will never change, and
it cannot reliably inspect secrets inside arbitrary body text. The HTTP
fetcher has separate DNS/IP/redirect security controls. Configure only
public sources with permission to repost their content.


## L2Dex partially rendered castle rows

A successfully downloaded ranking page is not necessarily complete. The
L2Dex adapter now requires each accepted castle row to include the observed
`Clan:` and `Attackers:` labels from the verified public table schema.
A **missing label** makes that row untrustworthy. It is skipped, preserving
any previously recorded owner/attacker information for that castle instead
of resetting the attacker set to empty.

An explicitly present label with an empty or `-` value still represents
the site's observed empty field; legitimate withdrawal followed by
re-registration continues to produce a new registration event. If **all**
rows become untrustworthy, parsing fails and the existing per-source
backoff applies. A trustworthy row from another castle on the same page
can still produce its own observed owner change.

This is conservative source-format validation, **not** verified proof of
a real-world siege or capture, and it cannot catch all transient wrong
values published by the game provider. Live accuracy checks remain open.


## L2Dex event identities during delayed delivery retries

L2Dex castle tracking intentionally **holds the previous ranking snapshot**
when any destination rejects a new event, so an unsuccessful destination can
retry. That means the same local `owner_generation` or `attack_generation`
number can describe **different** public observations if the ranking changes
again while a delivery is still pending.

Owner-change event IDs now combine the generation number with a short hash
of the observed **previous owner and new owner**. Siege-registration IDs
combine the generation number with a hash of the **previous attacker list
and newly registered attackers**. Retrying the *same* observation yields
the same ID, while an actual intervening new owner or different attacker
set gets a different receipt even if the generation has not advanced yet.

This fixes a specific lost-alert failure: after Telegram accepts owner B
but Discord fails, a later owner C will not be silently skipped by Telegram
because the earlier B receipt had the same generation number.

**Upgrade note:** This changes the receipt identity for newly observed
L2Dex owner/registration events without changing the existing JSON state
schema. Existing installed GitHub-only bots should upgrade after a
**successful polling cycle without pending L2Dex delivery errors**, so
there are no in-flight generation-only receipts from the old version.
If upgrading during a partial failure, a previous event might get one
extra retry under its new ID. This improvement cannot resurrect a previous
observation that vanished from the provider before its failed destination
recovered: durable public-news backlogs remain a separate P1 task.


## Populated but entirely unusable news snapshots

The new Community Bot distinguishes a truly empty public feed from one
that contains records that cannot be trusted. A valid empty RSS/Atom feed
or empty JSON array still means no articles are available. However, when
a populated RSS/Atom or JSON feed has **zero valid normalized articles**
(for example because every link contains a secret or the provider changed
its field types), the parser fails closed. Likewise, a generic HTML page
whose configured selector matches elements but yields only empty or
too-short content is **not** accepted as a successful baseline.

The existing per-parser retry cooldown is then used and **subscription
warm-start markers, delivery acknowledgements and other healthy sources
remain intact**. Once the provider returns valid data, the first
successful read can safely initialize a previously unwarmed source; only
subsequent new events are eligible for notification. Mixed feeds with
at least one trustworthy article continue publishing that article, while
unsafe entries are skipped.

This is a format/validation check, not proof of editorial accuracy,
permission to republish, or a replacement for ongoing source health
monitoring.


## Conflicting post identifiers in public feeds

RSS `guid`, Atom `id`, and JSON post `id` values are supplied by the
external publisher. A broken or inconsistent source can provide two
different posts with the **same normalized event identity** in one
snapshot. Taking the first or last would arbitrarily select a message
to deliver, and existing dedupe receipts could suppress the corrected
version later.

The Community Bot now quarantines **all** articles with such a duplicated
source event identity, including identical repeated entries. Distinct,
unambiguous articles in the same snapshot remain eligible for delivery.
If the snapshot contains no valid unambiguous events as a result, it is
handled as a source parsing failure and retried via the existing
per-parser cooldown, without warming the subscription or acknowledging
an arbitrary post. IDs are scoped to the selected world, source and
event kind, so two intentionally different event kinds can use the same
publisher's raw ID.

The check is conservative, and it does not detect aliases or content
changes that come with *different* IDs. Only valid normalized entries
are compared; independently rejected unsafe entries are not published.
