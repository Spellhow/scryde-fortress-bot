# Community sources and destinations (P1 library)

Status: reusable parsers, public HTTPS client, configuration and outbound publishers are implemented; automated GitHub-only community workflow is still a separate milestone. Existing BSOE production is unchanged.

## Configuration

Copy community.example.json to a private/community-specific configuration file in your own repository when the runner becomes available. The public JSON lists source URLs, game network, world, chronicle, destination **aliases**, and environment variable references. Do not put real Telegram chat IDs, bot tokens or Discord webhook URLs in committed JSON.

Supported source kinds:
- rss: public RSS or Atom feed, news text and article links.
- telegram_public: public t.me/s/<channel> pages only; not Telegram private groups.
- json_api: public JSON array or {"events":[...]} with id/title/body/url/kind.
- webpage: selected article/main HTML nodes; optional short CSS selector.
- l2dex_castles: reserved for a dedicated verified adapter; do not enable until the adapter exists.

Every source is scoped to a specific network and world. A subscription references an existing destination alias and the same game world; optional event_types, source_ids and clans restrict delivery.

The parser does not translate content by itself. A future AI/moderation layer will handle locale-specific output and prevent duplicate paid model calls.

## Network safety

The new client supports only HTTPS on port 443. It resolves all DNS answers and rejects non-global addresses, pins the public IP for the actual TLS connection (hostname verification remains enabled), refuses redirects, limits bodies to 512 KiB and enforces a short timeout. This does not authorize scraping websites that prohibit it. Polling frequency and source opt-in must respect provider terms.

## Outbound delivery

Telegram Bot API: destination uses address_env and token_env pointing to secret environment variables.
Discord: destination uses address_env pointing to an HTTPS discord.com/api/webhooks/... webhook secret. Webhook notifications are supported without an always-on host. Interactive slash commands will require a separate optional service.

The publisher sends plain source text (no HTML interpreted by Telegram), disables Discord role mentions, and returns success only for a confirmed response. Errors are sanitized to avoid printing tokens/webhooks. No delivery state stores a destination's real address.

## Operational status

The public multi-community runner, moderation workflow, fresh installation smoke test, and Scryde-to-core production cutover remain open milestones. GitHub-only schedule is best effort.
