# Scryde read-only shadow validation (P1-CORE)

The **existing BSOE Scryde x1000 bot stays the only authoritative publisher**. The new modular event core must be compared safely against its known decisions before cutover. This step implements an observational shadow projection with no network access or extra model calls.

## Turn on diagnostics (optional)

In a separate test/manual workflow, set runner environment variable `SCRYDE_SHADOW_DIAGNOSTICS=true`. The default is `false`. Do **not** set this on production before reviewing the extra log volume and privacy policy.

When the legacy runner already has a valid Scryde fortress/castle snapshot, it calls the pure parser *before* the existing alert/state handler. It logs only aggregate counts:

- observed valid rows and objects owned by the tracked clan;
- rows with a registration to attack as the tracked clan;
- previously owned IDs whose **present valid row** now names another owner;
- previously owned IDs **missing or invalid** in the current snapshot (always deferred, never interpreted as a loss);
- malformed/duplicate rows, which cannot prove a transition.

No names, raw response bodies, chat IDs, tokens or state contents are printed by the shadow summary. Shadow exceptions are sanitized to their Python type and **cannot block BSOE alerts**.

## Offline tests and cutover gate

`test_scryde_shadow.py` covers multiple owned objects, our attack registrations, verified ownership change, explicit NPC ownership, missing/invalid rows, duplicate IDs, malformed attackers, legacy flat-state compatibility, no mutation and source data privacy. These are deterministic fixtures, not live-source parity proof.

Next: compare legacy and new *event decisions* and exact Telegram copy against the same recorded real Scryde inputs; migration must preserve old dedupe, pending news/moderation queue, siege reminders and ownership state. Do not claim parity or enable a new publisher until the owner verifies such reports. Rollback simply disables the diagnostics flag.

The available renderer for new multi-community feeds is not yet a drop-in replacement for the existing BSOE moderation/Gemini pipeline; these should be migrated as separate features.



## Legacy fail-closed guards

The authoritative legacy handler now validates Scryde ranking rows before interpreting them as defensive or offensive siege evidence. Invalid/missing owner fields, partial attacker arrays and duplicate IDs cannot cause an **immediate cancellation or castle loss**. Missing rows are deferred as before; valid explicit NPC owners and complete owner changes continue through the original notification path. The offensive attack processor delays cancellation when a snapshot has malformed rows, preserving tracked state for the next valid snapshot.

These guards are independently tested in `test_scryde_fail_closed.py`, including valid negative and valid positive cases. Production remains on its original delivery/AI path. This is *not* an authorization to swap the current bot for the new core.
