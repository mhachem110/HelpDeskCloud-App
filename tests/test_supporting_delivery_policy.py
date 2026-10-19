"""Keep supporting-image publication and schema migration behind reviewed gates."""

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_workflow(path):
    workflow = yaml.safe_load((ROOT / path).read_text())
    # PyYAML's default YAML 1.1 resolver reads the GitHub Actions key `on` as True.
    return workflow, workflow.get("on", workflow.get(True))


class SupportingDeliveryPolicyTests(unittest.TestCase):
    def test_supporting_images_are_scanned_and_only_manually_published(self):
        workflow, triggers = load_workflow(".github/workflows/supporting-images-ci.yml")
        self.assertEqual(triggers["pull_request"]["branches"], ["dev"])
        self.assertEqual(triggers["push"]["branches"], ["dev"])
        self.assertIn("workflow_dispatch", triggers)

        validate = workflow["jobs"]["validate"]
        validate_script = "\n".join(step.get("run", "") for step in validate["steps"])
        self.assertIn("linux/amd64", validate_script)
        self.assertIn("pg_isready", validate_script)
        scans = [step["with"] for step in validate["steps"]
                 if step.get("uses", "").startswith("aquasecurity/trivy-action@")]
        self.assertEqual(len(scans), 2)
        for scan in scans:
            self.assertEqual(scan["severity"], "CRITICAL")
            self.assertEqual(scan["ignore-unfixed"], True)
            self.assertEqual(scan["exit-code"], "1")

        attest = workflow["jobs"]["attest"]
        self.assertIn("pull_request", attest["if"])
        publish = workflow["jobs"]["publish"]
        self.assertIn("github.repository == 'mhachem110/HelpDeskCloud-App'", publish["if"])
        self.assertIn("workflow_dispatch", publish["if"])
        self.assertIn("DEV_SUPPORTING_IMAGES_PUBLISH_ENABLED", publish["if"])
        self.assertIn("inputs.approve_publication == true", publish["if"])
        self.assertEqual(publish["environment"], "dev-supporting-images-publish")
        self.assertEqual(publish["permissions"]["id-token"], "write")
        steps = publish["steps"]
        verify = next(i for i, step in enumerate(steps)
                      if "Re-verify both image archive attestations" in step.get("name", ""))
        auth = next(i for i, step in enumerate(steps)
                    if str(step.get("uses", "")).startswith("google-github-actions/auth@"))
        self.assertLess(verify, auth)
        push_script = next(step["run"] for step in steps
                           if step.get("name", "").startswith("Verify immutable repository"))
        self.assertIn("immutableTags", push_script)
        self.assertIn("image_summary.digest", push_script)

    def test_migration_is_manual_explicitly_approved_and_never_replaces_job(self):
        workflow, triggers = load_workflow(".github/workflows/dev-db-migration.yml")
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        self.assertEqual(triggers["workflow_dispatch"]["inputs"]["confirmation"]["default"],
                         "DO NOT RUN")
        preflight = workflow["jobs"]["preflight"]
        preflight_script = "\n".join(step.get("run", "") for step in preflight["steps"])
        self.assertIn("DEV_DB_MIGRATION_ENABLED", preflight_script)
        self.assertIn("RUN helpdesk-dev-schema-001", preflight_script)

        execute = workflow["jobs"]["execute"]
        self.assertEqual(execute["environment"], "dev-db-migration")
        steps = execute["steps"]
        verify = next(i for i, step in enumerate(steps)
                      if "Verify the required GitHub Environment" in step.get("name", ""))
        auth = next(i for i, step in enumerate(steps)
                    if str(step.get("uses", "")).startswith("google-github-actions/auth@"))
        self.assertLess(verify, auth)
        migration_script = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("kubectl create --dry-run=server", migration_script)
        self.assertIn("kubectl create --namespace", migration_script)
        self.assertNotIn("kubectl delete", migration_script)
        self.assertNotIn("kubectl replace", migration_script)

        auth = next(step for step in steps
                    if str(step.get("uses", "")).startswith("google-github-actions/auth@"))
        self.assertEqual(auth["with"]["workload_identity_provider"],
                         "projects/260283083469/locations/global/workloadIdentityPools/"
                         "helpdesk-github/providers/github-app-migration-dev")
        self.assertEqual(auth["with"]["service_account"],
                         "helpdesk-app-migr-runner-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com")
        self.assertNotIn("cloudsql", migration_script.lower())
        self.assertNotIn("secretmanager", migration_script.lower())

    def test_migration_runner_rbac_is_namespace_scoped_and_read_limited(self):
        role, binding = list(yaml.safe_load_all(
            (ROOT / "k8s/dev-migration-runner-rbac.yaml").read_text()))
        self.assertEqual(role["kind"], "Role")
        self.assertEqual(role["metadata"]["namespace"], "helpdesk-dev")
        self.assertEqual(binding["kind"], "RoleBinding")
        self.assertEqual(binding["metadata"]["namespace"], "helpdesk-dev")
        self.assertEqual(binding["subjects"][0]["name"],
                         "helpdesk-app-migr-runner-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com")
        job_rule = next(rule for rule in role["rules"] if "jobs" in rule["resources"])
        self.assertEqual(job_rule["verbs"], ["get", "list", "watch", "create"])
        self.assertNotIn("update", job_rule["verbs"])
        self.assertNotIn("delete", job_rule["verbs"])
        for rule in role["rules"]:
            self.assertNotIn("*", rule["verbs"])


if __name__ == "__main__":
    unittest.main()
