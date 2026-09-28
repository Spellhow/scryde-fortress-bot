import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone


ROOT = pathlib.Path(__file__).resolve().parent
WATCHDOG = ROOT / "ops" / "dispatch_news_watchdog.sh"


class DispatchWatchdogTests(unittest.TestCase):
    def run_watchdog(self, runs):
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            bin_dir = tmp / "bin"
            bin_dir.mkdir()
            gh_log = tmp / "gh.log"
            runs_file = tmp / "runs.json"
            runs_file.write_text(json.dumps(runs), encoding="utf-8")

            fake_gh = bin_dir / "gh"
            fake_gh.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "printf '%s\\n' \"$*\" >> \"$FAKE_GH_LOG\"\n"
                "if [[ \"${1:-} ${2:-}\" == 'run list' ]]; then\n"
                "  cat \"$FAKE_GH_RUNS\"\n"
                "  exit 0\n"
                "fi\n"
                "if [[ \"${1:-} ${2:-}\" == 'workflow run' ]]; then\n"
                "  exit 0\n"
                "fi\n"
                "echo \"unexpected gh invocation: $*\" >&2\n"
                "exit 2\n",
                encoding="utf-8",
            )
            fake_gh.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{bin_dir}:{env['PATH']}",
                    "FAKE_GH_LOG": str(gh_log),
                    "FAKE_GH_RUNS": str(runs_file),
                    "SCRYDE_WATCHDOG_STATE_DIR": str(tmp / "state"),
                    "SCRYDE_GH_RETRIES": "1",
                    "SCRYDE_STALE_ACTIVE_MINUTES": "20",
                    "SCRYDE_STALE_SUCCESS_MINUTES": "30",
                    "SCRYDE_ALERT_COOLDOWN_SECONDS": "21600",
                }
            )
            proc = subprocess.run(
                ["bash", str(WATCHDOG)],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            log = gh_log.read_text(encoding="utf-8") if gh_log.exists() else ""
            return proc, log

    def test_stale_queued_run_does_not_block_new_dispatch(self):
        runs = [
            {
                "status": "queued",
                "conclusion": "",
                "createdAt": "2026-09-13T09:20:20Z",
                "updatedAt": "2026-09-13T09:20:20Z",
                "databaseId": 34749339649,
                "url": "https://example.invalid/stale",
            },
            {
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-09-13T08:50:00Z",
                "updatedAt": "2026-09-13T08:52:00Z",
                "databaseId": 1,
                "url": "https://example.invalid/old-success",
            },
        ]
        proc, log = self.run_watchdog(runs)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("workflow run siege-bot.yml", log)
        self.assertIn("workflow run news-bot.yml", log)
        self.assertIn("ignoring stale GitHub Actions run", proc.stderr)

    def test_fresh_active_run_and_recent_success_are_healthy(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs = [
            {
                "status": "queued",
                "conclusion": "",
                "createdAt": now,
                "updatedAt": now,
                "databaseId": 2,
                "url": "https://example.invalid/fresh",
            },
            {
                "status": "completed",
                "conclusion": "success",
                "createdAt": now,
                "updatedAt": now,
                "databaseId": 3,
                "url": "https://example.invalid/success",
            },
        ]
        proc, log = self.run_watchdog(runs)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("workflow run", log)
        self.assertIn("watchdog healthy", proc.stdout)


if __name__ == "__main__":
    unittest.main()
