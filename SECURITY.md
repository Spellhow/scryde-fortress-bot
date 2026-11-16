# Security policy

Please do not open public issues containing bot tokens, private chat IDs, credentials, server cookies, private community messages, or operational logs with secrets.

Use GitHub's private vulnerability reporting for this repository if enabled, or contact the maintainer privately through the GitHub profile. Include reproduction steps without posting working credentials. Rotate any accidentally disclosed token immediately; deleting a line from Git does not remove it from history.

## Deployment precautions
- Set `TG_TOKEN`, `TG_CHAT`, `TG_CHAT_DEBUG` and `GEMINI_API_KEY` as GitHub Actions **secrets**, not workflow literals or committed files.
- The current `site_state.json` is committed to this **public** repo. Do not add personal subscriber information, sensitive destination IDs or private content to it. A privacy-safe storage migration is tracked in `docs/IMPLEMENTATION_PLAN.md`.
- Keep `GITHUB_ONLY_MODE` disabled on a VPS-dispatched deployment unless its schedule is coordinated.
- Give Telegram/Discord bots only required channel permissions.
- New user-provided web feeds must validate URLs, redirects and destination IPs before fetching.
- Never enable arbitrary execution from news posts or AI-generated content.
- GitHub-only monitoring is best effort and not a safety-critical or guaranteed real-time alerting service.

Security and licensing audits remain open work items. Presence of this document does not imply a completed historical secret scan.
