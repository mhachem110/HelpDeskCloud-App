"""Check the credential boundary of the prepared Dev delivery workflow."""

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class DeliveryPolicyTests(unittest.TestCase):
    def test_only_trusted_dev_events_can_reach_cloud_jobs(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/app-dev-delivery.yml").read_text())
        triggers = workflow.get("on", workflow.get(True))  # PyYAML treats YAML 1.1 `on` as true.
        self.assertEqual(triggers["push"]["branches"], ["dev"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertNotIn("pull_request", triggers)
        self.assertNotIn("pull_request_target", triggers)
        package = workflow["jobs"]["package"]
        self.assertIn("vars.DEV_APP_CD_ENABLED == 'true'", package["if"])
        self.assertNotIn("id-token", package.get("permissions", {}))
        for name, environment in (("publish", "dev-app-publish"), ("deploy", "dev-app-deploy")):
            job = workflow["jobs"][name]
            self.assertEqual(job["environment"], environment)
            self.assertEqual(job["permissions"]["id-token"], "write")
            steps = job["steps"]
            verify = next(i for i, step in enumerate(steps) if "Verify protected" in step.get("name", ""))
            auth = next(i for i, step in enumerate(steps)
                        if str(step.get("uses", "")).startswith("google-github-actions/auth@"))
            self.assertLess(verify, auth)
            self.assertEqual(steps[verify]["env"]["EXPECTED_ENVIRONMENT"], environment)
            self.assertNotIn("helpdesk-terraform-dev@", str(job))
        self.assertNotEqual(str(workflow["jobs"]["publish"]["steps"]),
                            str(workflow["jobs"]["deploy"]["steps"]))

    def test_delivery_rbac_has_no_project_or_bootstrap_write(self):
        role, binding = list(yaml.safe_load_all((ROOT / "k8s/dev-delivery-rbac.yaml").read_text()))
        self.assertEqual(role["kind"], "Role")
        self.assertEqual(role["metadata"]["namespace"], "helpdesk-dev")
        self.assertEqual(binding["kind"], "RoleBinding")
        self.assertEqual(binding["subjects"][0]["name"],
                         "helpdesk-app-deployer-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com")
        for rule in role["rules"]:
            if "serviceaccounts" in rule["resources"] or "secretproviderclasses" in rule["resources"]:
                self.assertEqual(rule["verbs"], ["get"])
            self.assertNotIn("*", rule["verbs"])


if __name__ == "__main__":
    unittest.main()
