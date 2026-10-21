"""Repository-only changes must not auto-release or run database migrations."""

import fnmatch
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name):
    config = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return config.get("on", config.get(True)), config


class RepositoryWorkflowSafetyTests(unittest.TestCase):
    def test_this_repository_only_change_set_does_not_match_delivery_paths(self):
        triggers, _ = load_workflow("app-dev-delivery.yml")
        paths = triggers["push"]["paths"]
        changed = {
            ".github/scripts/verify-dotnet.sh",
            ".github/scripts/check-schema-parity.py",
            ".github/scripts/detect-ci-scope.py",
            ".github/workflows/app-ci.yml",
            ".github/workflows/app-dev-delivery.yml",
            ".github/workflows/dev-db-migration.yml",
            "tests/test_schema_parity.py",
            "tests/test_repository_workflow_safety.py",
            "tests/test_ci_scope.py",
            "README.md",
            "docs/CODE-WALKTHROUGH.md",
        }
        matched = {path for path in changed
                   if any(fnmatch.fnmatchcase(path, pattern) for pattern in paths)}
        self.assertEqual(matched, set())

    def test_database_migration_workflow_remains_manual_and_separate(self):
        triggers, config = load_workflow("dev-db-migration.yml")
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        execute = config["jobs"]["execute"]
        self.assertEqual(execute["environment"], "dev-db-migration")
        uses = [step.get("uses", "") for step in execute["steps"]]
        self.assertTrue(any("google-github-actions/auth@" in action for action in uses))
        self.assertIn("helpdesk-app-migr-runner-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com",
                      str(execute))
        self.assertNotIn("helpdesk-app-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com",
                         str(execute))

    def test_ci_and_release_share_dotnet_validation_while_release_stays_gated(self):
        _, ci = load_workflow("app-ci.yml")
        _, delivery = load_workflow("app-dev-delivery.yml")
        ci_uses_helper = any(step.get("run") == "bash .github/scripts/verify-dotnet.sh"
                             for step in ci["jobs"]["validate"]["steps"])
        package = delivery["jobs"]["package"]
        release_uses_helper = any(step.get("run") == "bash .github/scripts/verify-dotnet.sh"
                                  for step in package["steps"])
        self.assertTrue(ci_uses_helper)
        self.assertTrue(release_uses_helper)
        self.assertIn("vars.DEV_APP_CD_ENABLED == 'true'", package["if"])

    def test_all_application_workflow_yaml_files_parse(self):
        for path in WORKFLOWS.glob("*.yml"):
            with self.subTest(path=path.name):
                yaml.safe_load(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
