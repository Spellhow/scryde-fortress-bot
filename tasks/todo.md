# TODO

- [in_progress] Add forum updates source with x1000 Gemini filtering
- [pending] Persist forum post state and route through pending approval flow
- [pending] Verify forum parsing and syntax in production runner
- [completed] Add Scryde channel news parsing for x1000
- [completed] Integrate Gemini filtering and Ukrainian rewrite for server-specific news
- [completed] Persist processed news state and send translated posts to Telegram
- [in_progress] Verify workflow and syntax for new news pipeline
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
