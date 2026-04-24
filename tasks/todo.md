# TODO

- [completed] Add hybrid anti-bot fallback (requests + Playwright cookie solver)
- [completed] Verify parser behavior against challenge responses
- [completed] Validate Python syntax and dependency updates

## Verification notes

- Server `CentOS 7` has `glibc 2.17`, local Playwright driver cannot run.
- Docker fallback image was built, but solver containers hung and timed out in this environment.
