# Lessons Learned

- 2026-04-24: On CentOS 7 (`glibc 2.17`), local Python Playwright may crash/hang. Check `glibc` compatibility before choosing Playwright backend.
- 2026-04-24: Docker `subprocess.run(..., timeout=...)` can leave `docker run` containers alive after timeout; always add cleanup logic for labeled containers.
- 2026-05-01: For generated siege cards, preserve full attacker dictionaries from `siege_sides.attackers`; replacing them with a plain clan name or `image=None` removes clan emblems from the image.
- 2026-05-02: GitHub Actions runs using repo-committed state can duplicate alerts or fail state pushes unless each run rebases onto `origin/master` before reading and before pushing `site_state.json`.
- 2026-05-02: Telegram channel scraping via `https://t.me/s/<channel>` is sufficient for text-only public news ingestion; keep dedupe state by post id and offload server-specific filtering/translation to Gemini.
- 2026-05-02: For cross-source news reconciliation, prefer giving Gemini richer context and explicit decision outputs over encoding brittle similarity heuristics directly in Python.
- 2026-05-05: Gemini API frequently returns transient `503/UNAVAILABLE` under load; retry with backoff and do not spam debug alerts for known transient capacity errors.
- 2026-05-09: A clan can own multiple fortresses/castles at once; defence processing must track each owned object by id instead of stopping at the first owner match.
- 2026-05-13: Siege checks are time-sensitive; do not use long anti-bot backoff for fortress pages. Prefer one quick same-run retry and let the next scheduled run try again.
- 2026-05-13: GitHub Actions `playwright install --with-deps` can dominate run time because it invokes apt; for siege prefer cached Chromium install without `--with-deps`, and do not install browsers in news-only runs.
- 2026-05-15: Playwright `page.content()` can race Scryde client-side navigation and raise `page is navigating and changing the content`; retry content reads briefly and treat repeated races as no-data instead of failing the whole Siege workflow.
- 2026-05-15: For Scryde site updates, keep siege fetching page-isolated, prefer JS extraction of `#__NEXT_DATA__`, classify anti-bot/schema failures, and upload sanitized diagnostics artifacts for later inspection.
- 2026-06-05: News posts from Gemini/source HTML may contain Telegram-incompatible tags like `<br/>` or `<blockquote>`; sanitize outbound HTML, log Telegram response bodies, and fall back to plain text on Bot API 400 errors.
- 2026-06-05: Forum update parsing must not pin to an old XenForo page; resolve `/latest` and include the previous page so updates continue after pagination advances.
