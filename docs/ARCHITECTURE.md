# Architecture: incremental multi-world design

Status: core library under development. Production remains on github_runner.py and the existing Scryde workflows.

## Stable contracts implemented
- community.models.World differentiates game network, world/rates and chronicle.
- community.models.Event has explicit observed/scheduled/manual provenance, timezone-aware times, normalized per-world identity and a separate content revision fingerprint.
- Destination contains only a public alias and **names of environment variables** storing chat IDs/tokens/webhooks.
- Subscription filters events by world, type, source and clan; sender language is supplied to the delivery function.
- community.router.dispatch_events fans an already-fetched stream out to matching destinations and records only successful sends.
- community.state.DeliveryState stores schema-versioned hashed delivery IDs. It atomically saves JSON on disk; GitHub conflict-aware commit/rebase is a separate operation. This versioned state is not yet a migration of the legacy site_state.json.
- community.adapters.ScrydeRankingAdapter is a read-only normalizer for observed siege registrations; the legacy implementation decides all actual BSOE alerts. It does not invent ownership losses based on absent rows.

## Future boundaries
Source adapters fetch/normalize once per source, the core decides relevance and deduplication, moderator queues control publication, and Telegram/Discord transports render/send. New destinations cannot change source polling frequency.

## Limitations
- The existing BSOE runner is unchanged; no production cutover or multi-community live deployment.
- Crash after a remote send but before persisting state can result in a duplicate. Exactly-once network delivery is not guaranteed.
- No live Discord integration, AI translation cache, L2Dex parsing or arbitrary RSS/web API ingestion in this milestone.
- The public core state deliberately holds no private user identities, credentials or messages. Implementations must not serialize secret environment values.
- GitHub Actions cron is best-effort and not a reliable real-time siege alert service.
- A source adapter that sees a missing ranking row cannot infer a castle loss. Verified ownership change is required.

## Local pure-Python tests

    python3 -m unittest -v test_community_core

Uses only the Python standard library. See the parent implementation plan for rollout gates.
