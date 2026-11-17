# Outbound delivery acknowledgement contract

Status: **offline transport contracts verified; actual messages to an authorized remote channel remain to be tested**.

GitHub-only Community Bot uses the same source snapshot and per-destination delivery keys for Telegram and Discord. A successful HTTP request alone is **not** proof that a message was created:

- **Telegram**: expect HTTP 200, JSON `ok: true`, and a positive integer `result.message_id`.
- **Discord webhooks**: send with `wait=true`, disable all automatic role/user mentions, and require HTTP 200/201 with a decimal `id` returned by Discord.
- Empty, malformed, permission-denied, rate-limited, missing-token, and ambiguous responses are treated as **not confirmed**. The per-destination delivery key is not recorded, so the bot can retry on its next scheduled run.
- Credentials and webhook URLs remain in GitHub Secrets. The router exposes only the destination alias and sanitized failure class.
- Message text is conservatively truncated to fit Telegram and Discord limits, including emoji-heavy text (UTF-16 surrogate pairs count as two units). Very long source URLs are omitted instead of breaking the message limit.
- Discord webhook destinations must point to an official HTTPS Discord webhook URL; arbitrary domains and query strings are rejected.

**Crash window:** a remote platform can accept a message before GitHub persists the resulting delivery state. On a crash at that exact point, a later run can resend the same event. The system offers best-effort deduplication, **not mathematically exact-once delivery**.

## Verification

`test_transport_delivery.py` exercises the transport with fabricated, offline API responses and an end-to-end scenario in which Telegram accepts a new post, Discord returns HTTP 429, state is saved, the worker restarts, and only Discord is retried. No real Telegram or Discord messages are sent during tests.

**Next operational gate:** use an owner-authorized dedicated test channel and webhook. Validate that one new synthetic/fixture event appears, survives an intentional failure/retry, and does not duplicate on the next schedule tick. Never send a synthetic event to the current BSOE production channel without explicit authorization.
