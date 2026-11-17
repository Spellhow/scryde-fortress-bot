# Discord delivery (GitHub-only)

The Community Bot sends outbound Discord messages through an authorized webhook. In the basic installation you do not need a persistent Discord bot, server or Docker container.

## Setup and verified delivery

1. Create a webhook for a channel you administer in Discord. Store the full webhook URL as a GitHub Actions **Secret** named `DISCORD_WEBHOOK`. Never commit the URL to `community.json`.
2. Configure the destination as `{"id":"clan-discord","kind":"discord","address_env":"DISCORD_WEBHOOK"}` and subscribe it to the appropriate world and event types.
3. Set GitHub Actions variable `COMMUNITY_MODE=true`. Run **Test Community Delivery (manual)** in your own template repository and confirm one test message. This workflow is blocked in the original BSOE repository.
4. Once received, enable `RUN_GITHUB_SCHEDULE=true`. GitHub scheduling is best effort and can be delayed.

## Native embeds (optional)

The default remains a plain text message. To enable Discord's native rich embed for source events, add repository Actions variable:

```text
COMMUNITY_DISCORD_EMBEDS=true
```

This is a **variable**, not a secret. The webhook URL itself remains secret.

In embed mode, the bot publishes one title/description with the configured world, provenance (`observed`, `scheduled`, or `manual`) and UTC check time. The event start time, when provided, is shown with an explicit UTC label. Only **observed** events include a source URL, and only if the URL is a bounded public HTTPS link. Manual and scheduled reminders never display the project homepage as fabricated event evidence.

Discord message creation still uses `wait=true` and requires a response containing a message ID. Both text and embed modes set `allowed_mentions={"parse":[]}` to avoid automatically pinging roles/users or `@everyone` from third-party source text. Titles and descriptions are truncated within Discord embed limits, including supplementary Unicode emoji.

Docs: [Discord Execute Webhook](https://github.com/discord/discord-api-docs/blob/main/developers/resources/webhook.mdx).

## Limits

Forum/media channels can require a specific thread or a new thread name. The basic one-destination webhook sender does not yet configure threads, interactive buttons, slash commands, Discord roles or gateway presence. Those capabilities require a separate integration and possibly an always-on process. A webhook is not proof that the app holds administrator privileges on an entire Discord server.
