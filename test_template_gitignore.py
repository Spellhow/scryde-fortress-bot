"""Clean-copy git add must not omit reusable modules accidentally."""
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent


class TemplateGitignoreTests(unittest.TestCase):
    def is_ignored(self, path):
        completed = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", "--", path],
            cwd=ROOT, capture_output=True, text=True,
        )
        if completed.returncode not in (0,1):
            self.fail("git check-ignore failed unexpectedly")
        return completed.returncode == 0

    def test_library_config_module_not_ignored(self):
        self.assertFalse(self.is_ignored("community/config.py"))
        self.assertFalse(self.is_ignored("community/state.py"))
        self.assertFalse(self.is_ignored("community/adapters/l2dex.py"))
        self.assertFalse(self.is_ignored("scripts/setup_community.py"))

    def test_private_legacy_root_config_still_ignored(self):
        self.assertTrue(self.is_ignored("config.py"))
        self.assertTrue(self.is_ignored("state.json"))
        self.assertTrue(self.is_ignored(".env"))
        self.assertTrue(self.is_ignored("fortress_bot.log"))


if __name__ == "__main__":
    unittest.main()
