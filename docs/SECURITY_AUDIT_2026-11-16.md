# P0 source/history security audit (2026-11-16)

Scope: `Spellhow/scryde-fortress-bot`, including 6,077 Git commits at the observed baseline. Checks were read-only; no credentials were printed.

## Automated findings

- Reviewed 169 unique historical text blobs from code/config/docs, excluding historical `site_state.json` versions.
- Searched for commonly formatted Telegram bot tokens, Google AI keys, GitHub access tokens, OpenAI keys and PEM private-key headers. **No matches** in this limited scan.
- Earlier tracked-current-files scan of 30 paths also reported no matches for these patterns.
- The working repository has no tracked `.env` or `config.py` based on file inventory.
- `site_state.json` remains public and contains production-derived ownership, processed-news metadata and pending queues. Historical state revisions require a separate private-data review.

## Limitations / next checks

This is not a comprehensive secret audit. The regex scan can miss arbitrary passwords, URLs with access tokens, chat IDs, entropy-based secrets and personal text. Historical `site_state.json` blobs were excluded to avoid scanning 6,000+ frequent state commits on a shared production host. Review them in a bounded, off-host scanner if retention/privacy warrants it. Rotate any exposed credentials before rewriting history.

Repo metadata can be public, but private subscriber settings must never be added to `site_state.json`. Additional historical privacy review and third-party media/license review remain open in `IMPLEMENTATION_PLAN.md`.
