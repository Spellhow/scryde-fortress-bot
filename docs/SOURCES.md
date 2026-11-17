# Community sources and destinations (P1 library)

Status: reusable parsers, public HTTPS client, configuration and outbound publishers are implemented; an opt-in GitHub-only workflow is present for new community feeds. Existing BSOE production is unchanged.

## Configuration

Copy community.example.json to a private/community-specific configuration file in your own repository when the runner becomes available. The public JSON lists source URLs, game network, world, chronicle, destination **aliases**, and environment variable references. Do not put real Telegram chat IDs, bot tokens or Discord webhook URLs in committed JSON.

Supported source kinds:
- rss: public RSS or Atom feed, news text and article links.
- telegram_public: public t.me/s/<channel> pages only; not Telegram private groups.
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
