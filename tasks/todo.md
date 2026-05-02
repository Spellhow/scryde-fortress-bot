# TODO

- [completed] Fix duplicate siege notifications across GitHub Actions runs
- [completed] Sync latest state in workflow before run and before push
- [completed] Fix missing clan emblem on generated attack cards
- [completed] Verify generated card builder now receives attacker image for our clan
- [completed] Add hybrid anti-bot fallback (requests + Playwright cookie solver)
- [completed] Verify parser behavior against challenge responses
- [completed] Validate Python syntax and dependency updates

## Verification notes

- Server `CentOS 7` has `glibc 2.17`, local Playwright driver cannot run.
- Docker fallback image was built, but solver containers hung and timed out in this environment.
- Our attack card path must use the full attacker object from `siege_sides.attackers`; synthesizing `{"name": OUR_CLAN, "image": None}` drops the clan emblem on the card.
- GitHub Actions can send duplicate alerts when a run reads stale `site_state.json`; sync from `origin/master` and keep a recent alert fingerprint in state.
