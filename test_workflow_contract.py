"""Offline contract tests for opt-in schedules and current dispatch compatibility."""

from pathlib import Path
import unittest


WORKFLOW_DIR = Path(__file__).resolve().parent / ".github" / "workflows"


class WorkflowContractTests(unittest.TestCase):
    def test_scheduled_runs_are_opt_in(self):
        for name in ("news-bot.yml", "siege-bot.yml"):
            with self.subTest(workflow=name):
                content = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
                self.assertIn("workflow_dispatch:", content)
                self.assertIn("schedule:", content)
                self.assertIn("RUN_GITHUB_SCHEDULE", content)
                self.assertIn(
                    "github.event_name != 'schedule' || vars.RUN_GITHUB_SCHEDULE == 'true'",
                    content,
                )
                self.assertIn("group: scryde-state", content)
                self.assertIn("cancel-in-progress: false", content)

    def test_template_state_isolated_and_persisted(self):
        for name in ("news-bot.yml", "siege-bot.yml"):
            with self.subTest(workflow=name):
                content = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
                self.assertIn(
                    "github.repository == 'Spellhow/scryde-fortress-bot' && 'site_state.json' || 'community_state.json'",
                    content,
                )
                self.assertIn('if [ ! -f "$STATE_FILE" ]; then', content)
                self.assertIn('./ops/persist_state_with_retry.sh "$STATE_FILE"', content)
                self.assertNotIn("          STATE_FILE: site_state.json", content)

    def test_community_mode_disables_legacy_workflows(self):
        for name in ("news-bot.yml", "siege-bot.yml"):
            with self.subTest(name=name):
                content = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
                self.assertIn("vars.COMMUNITY_MODE != 'true'", content)

    def test_community_runner_persists_state_after_partial_failures(self):
        content = (WORKFLOW_DIR / "community-bot.yml").read_text(encoding="utf-8")
        self.assertIn("vars.COMMUNITY_MODE == 'true'", content)
        self.assertIn("continue-on-error: true", content)
        self.assertIn("always() && vars.COMMUNITY_DRY_RUN != 'true'", content)
        self.assertIn("steps.community_run.outcome == 'failure'", content)
        self.assertIn("community_deliveries.json", content)

    def test_setup_workflow_writes_only_fresh_template_config(self):
        config = (WORKFLOW_DIR / "setup-community.yml").read_text(encoding="utf-8")
        self.assertIn("github.repository != 'Spellhow/scryde-fortress-bot'", config)
        self.assertIn("github.event.repository.default_branch", config)
        self.assertIn("python scripts/setup_community.py", config)
        self.assertIn("SETUP_SOURCE_URL: ", config)
        self.assertIn("git add community.json", config)
        self.assertNotIn("git add .", config)

    def test_supported_schedule_variable_name_across_workflows(self):
        # GitHub refuses creation of repository variables beginning GITHUB_.
        # A real clean-install smoke test caught the legacy GITHUB_ONLY_MODE.
        for name in ("news-bot.yml", "siege-bot.yml", "community-bot.yml"):
            with self.subTest(name=name):
                data=(WORKFLOW_DIR / name).read_text(encoding="utf-8")
                self.assertIn("vars.RUN_GITHUB_SCHEDULE", data)
                self.assertNotIn("vars.GITHUB_ONLY_MODE", data)

    def test_setup_keyword_input_preserves_github_dispatch_limit(self):
        text=(WORKFLOW_DIR/"setup-community.yml").read_text(encoding="utf-8")
        self.assertIn("SETUP_INCLUDE_KEYWORDS:",text)
        self.assertIn("      include_keywords:",text)

    def test_news_and_siege_have_distinct_10_minute_offsets(self):
        news = (WORKFLOW_DIR / "news-bot.yml").read_text(encoding="utf-8")
        siege = (WORKFLOW_DIR / "siege-bot.yml").read_text(encoding="utf-8")
        self.assertIn("7,17,27,37,47,57 * * * *", news)
        self.assertIn("2,12,22,32,42,52 * * * *", siege)


if __name__ == "__main__":
    unittest.main()
