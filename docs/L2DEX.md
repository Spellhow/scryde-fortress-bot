# L2Dex castle adapter: New-Interlude x25

Status: **opt-in**. Runs within the existing GitHub-only Community Bot; no dedicated server required. The legacy BSOE/Scryde tracker remains unchanged.

## Verified public source (2026-11-17)

- URL: https://lineage2dex.com/en/rating/new-interlude.343
- Section identifier: `tab-top_castle`, HTML table headings `ID`, `Picture`, `Name`, `Info`, `Date`, `Siege`.
- Observed columns: nine castle IDs, castle names, owner clan and leader, displayed siege date, and registered attackers/defenders.
- The displayed siege dates have **no verified timezone**. The adapter preserves the literal display string and never converts it to UTC.
- The public page showed no registered attackers during the 2026-11-17 inspection. Live detection of a new registration remains unverified, although fixture tests pass.
- The table is **not live combat telemetry**. There is no basis for detecting real-time attacks, ownership losses from absent rows, or successful sieges solely from this data.

## Safe event semantics

The first valid snapshot establishes a silent baseline. Each later valid snapshot is compared against the previous one, using the same state file as the GitHub-only runner.

- `castle_owner_change`: emitted only if **both** previously observed and current owner names are non-empty and differ. Body says the owner *changed between observations*, not that a specific clan won an observed battle.
- `siege_registration`: emitted when new attacker clan names appear in the registration column. Body explicitly says this is not a live attack.
- Missing castle rows, missing owner names, malformed HTML, and site challenges **never** imply a loss. Empty/invalid tables fail closed and preserve stored state.
- Each castle's owner and attacker-registration generation increments on verified changes, so a later change back to an earlier state still generates a distinct event ID.
- Delivery is deduplicated per destination. If one destination fails, the source snapshot stays at its previous state and that destination can retry the same event on the next run; successful deliveries do not repeat.

## Example configuration

Use `community.example.json` and opt in to the existing `l2dex-new-interlude-castles` source by setting `"enabled": true`. Keep `COMMUNITY_MODE=true` and `GITHUB_ONLY_MODE=true` as repository **variables** and Telegram/Discord destinations as **secrets**. Do not enable the legacy Scryde tracker simultaneously in that repository.

World identity for the example is `network: L2Dex`, `name: New-Interlude x25`, `chronicle: Interlude`. A different L2Dex game world needs its own ranking page and source ID, not just a changed display name.

For other L2Dex worlds, inspect the public ranking and confirm that the same castle section and world-specific URL are present before enabling automatic publication. The source URL is restricted to `https://lineage2dex.com/{en,ru}/rating/<world>.<number>`.

## Test and rollout status

The parser was run read-only against the live public page on 2026-11-17 and identified nine castle rows, nine displayed owners and siege timestamps; no messages were sent. `test_l2dex_adapter.py` verifies DOM layout and safe transitions. `test_community_runner.py` checks retries, two destinations and malformed-source handling with offline fixtures.

Outstanding: verify actual change notifications with an authorized test channel, collect a real sample of multi-clan registration markup, check the provider's acceptable monitoring rate, and complete the clean GitHub-only template install smoke test. Until then, prefer testing with `COMMUNITY_DRY_RUN=true` and leave the example disabled by default.
