# Lessons Learned

- 2026-04-24: On CentOS 7 (`glibc 2.17`), local Python Playwright may crash/hang. Check `glibc` compatibility before choosing Playwright backend.
- 2026-04-24: Docker `subprocess.run(..., timeout=...)` can leave `docker run` containers alive after timeout; always add cleanup logic for labeled containers.
