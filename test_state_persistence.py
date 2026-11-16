"""Regression: a GitHub template's initially untracked state must be persisted."""

import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent
PERSIST = ROOT / "ops" / "persist_state_with_retry.sh"


def git(directory, *args):
    return subprocess.run(
        ["git", *args], cwd=directory, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ).stdout.strip()


class StatePersistenceTests(unittest.TestCase):
    def test_new_state_is_pushed_once_and_unchanged_state_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            bare = base / "remote.git"
            work = base / "work"
            work.mkdir()
            subprocess.run(
                ["git", "init", "--bare", "--initial-branch=master", str(bare)],
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            git(work, "init", "--initial-branch=master")
            git(work, "config", "user.name", "Test")
            git(work, "config", "user.email", "test@example.invalid")
            (work / "README").write_text("test", encoding="utf-8")
            git(work, "add", "README")
            git(work, "commit", "-m", "initial")
            git(work, "remote", "add", "origin", str(bare))
            git(work, "push", "-u", "origin", "master")
            (work / "community_state.json").write_text('{"meta":{}}', encoding="utf-8")
            env = dict(os.environ, STATE_PUSH_MAX_ATTEMPTS="1")
            first = subprocess.run(
                ["bash", str(PERSIST), "community_state.json"],
                cwd=work, env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, first.returncode, first.stderr + first.stdout)
            self.assertEqual(
                "community_state.json",
                git(work, "ls-files", "community_state.json"),
            )
            after_first = git(work, "rev-parse", "HEAD")
            second = subprocess.run(
                ["bash", str(PERSIST), "community_state.json"],
                cwd=work, env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, second.returncode, second.stderr + second.stdout)
            self.assertIn("No state changes", second.stdout)
            self.assertEqual(after_first, git(work, "rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()
