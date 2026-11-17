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


## Follow-up scan (2026-11-17)

A low-priority streaming scan examined **all 5,973 historical `site_state.json` blob versions**, approximately 714.6 MB. No matches were found for commonly formatted Telegram/Google/GitHub/OpenAI tokens, PEM private keys, standard private chat-ID JSON fields or email addresses. The scan returned only counts, never matching values. This completes the bounded regex-based scan that was intentionally omitted in the first pass.

The remaining security task is a human review of non-standard secrets, personal messages, unusual identifiers and third-party media/license constraints. A negative regex scan does **not** certify that 6,000+ public versions contain no personal data. Do not remove state history without a separate migration/rotation decision.
