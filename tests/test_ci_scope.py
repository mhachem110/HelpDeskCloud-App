import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "detect-ci-scope.py"
spec = importlib.util.spec_from_file_location("ci_scope", SCRIPT)
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class CiScopeTests(unittest.TestCase):
    def test_documentation_does_not_select_build_or_manifest_checks(self):
        changed = {"README.md", "docs/ARCHITECTURE.md"}
        for workflow, groups in scope.GROUPS.items():
            for group in groups:
                self.assertFalse(scope.group_is_relevant(workflow, group, changed), (workflow, group))

    def test_application_and_iap_source_select_dotnet_and_container_validation(self):
        changed = {"src/HelpDeskCloud/Security/IapAssertionValidator.cs"}
        self.assertTrue(scope.group_is_relevant("app-ci", "dotnet", changed))
        self.assertTrue(scope.group_is_relevant("app-ci", "container", changed))

    def test_helm_and_policy_changes_select_manifest_validation(self):
        for path in ("helm/helpdesk/templates/deployment.yaml", "k8s/dev-delivery-rbac.yaml",
                     "tests/test_https_edge.py", ".github/scripts/check-https-edge.py"):
            self.assertTrue(scope.group_is_relevant("app-ci", "helm", {path}), path)

    def test_supporting_image_changes_do_not_select_the_application_container_group(self):
        changed = {"database/migration-client/Dockerfile"}
        self.assertTrue(scope.group_is_relevant("supporting-images", "supporting_images", changed))
        self.assertFalse(scope.group_is_relevant("app-ci", "container", changed))

    def test_dockerfile_changes_select_both_container_validation_paths(self):
        changed = {"Dockerfile"}
        self.assertTrue(scope.group_is_relevant("app-ci", "container", changed))
        self.assertFalse(scope.group_is_relevant("supporting-images", "supporting_images", changed))

    def test_unavailable_event_diff_fails_open(self):
        self.assertTrue(scope.group_is_relevant("app-ci", "dotnet", None))
        self.assertTrue(scope.group_is_relevant("supporting-images", "supporting_images", None))

    @patch.object(scope.subprocess, "run", side_effect=scope.subprocess.CalledProcessError(1, "git"))
    def test_git_diff_failure_enables_all_checks(self, _run):
        self.assertIsNone(scope.changed_paths("pull_request", "", "base", "head"))


if __name__ == "__main__":
    unittest.main()
