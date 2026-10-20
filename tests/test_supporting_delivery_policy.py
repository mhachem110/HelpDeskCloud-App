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
        inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["mode"]["options"], ["diagnostic", "migration"])
        self.assertEqual(inputs["mode"]["default"], "migration")
        self.assertEqual(inputs["confirmation"]["default"], "DO NOT RUN")
        preflight = workflow["jobs"]["preflight"]
        preflight_script = "\n".join(step.get("run", "") for step in preflight["steps"])
        self.assertIn("DEV_DB_MIGRATION_ENABLED", preflight_script)
        self.assertIn("RUN helpdesk-dev-schema-001", preflight_script)
        self.assertIn("DIAGNOSE helpdesk-dev-gke", preflight_script)
        self.assertIn("diagnostic)", preflight_script)
        self.assertIn("migration)", preflight_script)
        diagnostic_gate = preflight_script.split("diagnostic)", 1)[1].split("migration)", 1)[0]
        migration_gate = preflight_script.split("migration)", 1)[1].split("*)", 1)[0]
        self.assertNotIn("ENABLED", diagnostic_gate)
        self.assertIn('[[ "$ENABLED" == \'true\' ]]', migration_gate)
        self.assertIn('[[ "$CONFIRMATION" == \'DIAGNOSE helpdesk-dev-gke\' ]]', diagnostic_gate)

        render = workflow["jobs"]["render"]
        self.assertEqual(render["if"], "inputs.mode == 'migration'")
        execute = workflow["jobs"]["execute"]
        self.assertEqual(execute["environment"], "dev-db-migration")
        self.assertIn("inputs.mode == 'diagnostic'", execute["if"])
        self.assertIn("needs.preflight.result == 'success'", execute["if"])
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

    def test_diagnostic_mode_is_read_only_and_cannot_fall_through_to_migration(self):
        workflow, _ = load_workflow(".github/workflows/dev-db-migration.yml")
        jobs = workflow["jobs"]
        self.assertEqual(jobs["render"]["if"], "inputs.mode == 'migration'")
        execute = jobs["execute"]
        diagnostic_steps = [step for step in execute["steps"]
                            if "diagnostic" in step.get("name", "").lower()
                            or step.get("id", "").endswith("diagnostics")]
        self.assertEqual(len(diagnostic_steps), 2)
        preflight = next(step for step in diagnostic_steps
                         if step.get("id") == "plugin-diagnostics")
        self.assertEqual(
            preflight["continue-on-error"], "${{ inputs.mode == 'diagnostic' }}"
        )
        self.assertEqual(preflight["env"]["GKE_IAM_PROPAGATION_RETRY_SECONDS"], 480)
        for step in diagnostic_steps:
            if step.get("name") == "Finish diagnostics without entering the migration path":
                self.assertIn("always()", step["if"])
                self.assertIn("inputs.mode == 'diagnostic'", step["if"])
            else:
                self.assertNotIn("if", step)
        for name in ("Recheck target and bootstrap objects with the approved identity",
                     "Dry-run and create the Job once; never replace an existing Job"):
            step = next(step for step in execute["steps"] if step.get("name") == name)
            self.assertEqual(step["if"], "inputs.mode == 'migration'")

        credentials = [step for step in execute["steps"]
                       if str(step.get("uses", "")).startswith("google-github-actions/get-gke-credentials@")]
        self.assertEqual(credentials, [])

        plugin_config = next(step for step in execute["steps"]
                             if step.get("name") == "Generate supported DNS-endpoint kubeconfig with the GKE exec plugin")
        self.assertIn("gcloud container clusters get-credentials", plugin_config["run"])
        self.assertIn("--dns-endpoint", plugin_config["run"])
        self.assertIn("container/use_application_default_credentials true", plugin_config["run"])
        finish = next(step for step in execute["steps"]
                      if step.get("name") == "Finish diagnostics without entering the migration path")
        self.assertEqual(finish["env"]["PLUGIN_RESULT"], "${{ steps.plugin-diagnostics.outcome }}")
        self.assertNotIn("TOKEN_RESULT", finish["env"])
        self.assertIn("exit 1", finish["run"])

        script = (ROOT / ".github/scripts/diagnose-dev-migration-connectivity.py").read_text()
        self.assertIn('"get", "--raw=/version"', script)
        self.assertIn('"auth", "whoami", "-o", "json"', script)
        self.assertIn('"auth",\n            "can-i"', script)
        for mutating_command in ("kubectl create", "kubectl apply", "kubectl replace", "kubectl delete"):
            self.assertNotIn(mutating_command, script)
        self.assertNotIn("print(result.stderr)", script)
        self.assertNotIn("print(result.stdout)", script)
        self.assertIn("oauth2.googleapis.com/tokeninfo", script)
        self.assertIn("data=urlencode({\"access_token\": token})", script)
        self.assertIn(
            "return 0 if adc_identity_ok and target_ok and credential_ok and api_ok else 1",
            script,
        )

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
