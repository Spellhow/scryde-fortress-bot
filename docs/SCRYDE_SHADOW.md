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



## Shared ranking normalization extraction

`community/adapters/scryde_rows.py` now defines the single **stdlib-only row validation** contract used by the authoritative legacy Scryde runner, read-only shadow projection, and the new read-only siege registration adapter. The existing public helper names in `github_runner.py` remain as compatibility wrappers.

This eliminates one significant source of drift: a missing owner field cannot be interpreted as an explicit NPC owner in the shadow module while the legacy runner rejects it as malformed. Duplicate IDs are quarantined in the same way for both paths. Tests in `test_scryde_shared_rows.py` and existing legacy regressions verify the shared trust boundary.

**Not yet migrated:** the actual BSOE alert state machine, siege reminder copy, news moderation/approvals, Telegram sending and existing `site_state.json` persistence. They remain under the legacy runner until event-by-event parity has been checked.


## Candidate event parity (before any cutover)

`community/adapters/scryde_decisions.py` projects the **candidate Telegram sends** from the same already-fetched snapshot and previous legacy state, without mutating state, fetching pages or invoking the publisher. It covers defence-attack starts, attacker/time changes, early siege reminders, explicit ownership losses, offensive registrations, offensive reminders and cancellation. Legacy three-hour duplicate-alert cache and malformed-row fail-closed deferrals are considered.

The optional `SCRYDE_SHADOW_DIAGNOSTICS=true` flag now logs **only event-type counters** alongside the previous read-only ownership counts, and remains **disabled by default**. No owner/clan names, chat identifiers or source content are included in these candidate summaries.

`test_scryde_decision_parity.py` compares predicted candidate categories against real (mocked, no network) legacy `process_defence` and `process_our_attacks` send attempts across deterministic cases. This is stronger than count-only shadowing, but **not equivalent to proving exact message copy, Gemini moderation parity or live event delivery**. A production cutover remains blocked until recorded real inputs and a dual-run replay confirm exact outcomes.



## Retry guarantee for failed negative alerts

The legacy BSOE decision engine now keeps an outstanding **defence cancellation** or **ownership loss** pending when `send_notification` returns false. It does **not** clear the siege/ownership flags before Telegram confirms success. The next valid ranking snapshot retries the negative notification. Once confirmed it updates state and does not send again for the same observed transition.

For an attack that has already reached its scheduled start time, cancelling the prior alert is no longer relevant: the old state expires silently, preserving the existing behavior.

This is verified with offline transport mocks across both fortresses and castles (`test_scryde_delivery_retry.py`). A real Telegram confirmation and production delivery smoke remain unverified. A crash between platform acceptance and saving Git state can still create a duplicate, as described in the delivery contract.


## Shared decision rules (incremental P1-CORE)

The authoritative BSOE sender and the read-only Community Bot projector now use the same pure module, `community/adapters/scryde_siege_rules.py`, for the following alert eligibility decisions:

- defence registration changes (attacking clans or siege time), early defence reminders, and cancellation versus already-finished siege;
- our outbound attack registration/date changes, early reminders, and vanished registrations that either expire silently after the scheduled start or require an actual cancellation notice.

The module has no network, AI, state writes or platform dependencies. It does not decide whether Telegram accepted a message. Legacy BSOE still owns publication, exact Ukrainian copy, last-alert timestamps, and the authoritative `site_state.json`. The read-only projection can now compare decisions against the same boundary conditions in offline regression tests.

This is **not a production cutover**: full state transition/replay parity, real ranking evidence and authorized delivery tests remain required. If a regression appears, revert this shared-rule refactor; the file state schema and GitHub schedule have not changed.


## Verifying our attack registration cancellation

The legacy BSOE offensive siege handler formerly treated *absence of the
previously attacked object from a ranking page* as proof that the clan had
withdrawn. That can be misleading when the page is incomplete or an object
temporarily disappears.

A cancellation notice now requires a **present, valid, same-object ranking
row** where BSOE is not listed among the attackers and the current owner is
not BSOE. A missing/invalid/duplicated row is not evidence of withdrawal;
the old registration state remains retryable. If the row explicitly names
BSOE as the new owner, the old offensive registration is retired **without**
announcing a withdrawal or inventing a victory event. Registrations that have
reached their scheduled siege time expire silently, even if their row is no
longer present.

These conditions are shared by the legacy sender and the pure read-only
candidate projector. The sender still requires a confirmed Telegram send
before deleting a cancellation registration. Offline tests cover both
castles and fortresses, malformed snapshots, same-owner transitions, failed
sends and expiry. This is a deliberate accuracy fix to the old behavior,
not proof of full state machine migration.
