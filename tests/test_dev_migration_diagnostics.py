"""Regression tests for sanitized GKE migration connectivity diagnostics."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github/scripts/diagnose-dev-migration-connectivity.py"
SPEC = importlib.util.spec_from_file_location("dev_migration_diagnostics", SCRIPT)
DIAGNOSTICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTICS)


class DiagnosticClassificationTests(unittest.TestCase):
    def test_classifies_google_dns_frontend_html_403_without_echoing_body(self):
        response = "<!doctype html><title>403 Forbidden</title>Google frontend error"
        result = subprocess.CompletedProcess(["kubectl"], 1, "", response)
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result), "google-dns-frontend-http-403"
        )

    def test_frontend_403_takes_precedence_over_plugin_wrapper_text(self):
        result = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            "",
            "<!doctype html><title>403 Forbidden</title>gke-gcloud-auth-plugin",
        )
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result), "google-dns-frontend-http-403"
        )

    def test_classifies_kubernetes_status_forbidden_as_authorization(self):
        response = '{"kind":"Status","apiVersion":"v1","status":"Failure","reason":"Forbidden","code":403}'
        result = subprocess.CompletedProcess(["kubectl"], 1, response, "")
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result),
            "kubernetes-authorization-forbidden",
        )

    def test_classifies_kubectl_forbidden_message_as_authorization(self):
        result = subprocess.CompletedProcess(
            ["kubectl"], 1, "", "Error from server (Forbidden): cannot get resource"
        )
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result),
            "kubernetes-authorization-forbidden",
        )

    def test_classifies_missing_gke_auth_plugin_without_echoing_stderr(self):
        result = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            "",
            "exec: executable gke-gcloud-auth-plugin not found; access_token=do-not-print-this",
        )
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result),
            "gke-auth-plugin-executable-unavailable",
        )
        lines = []
        DIAGNOSTICS.record_api_check(lines, "Kubernetes API probe", result)
        self.assertNotIn("do-not-print-this", "\n".join(lines))

    def test_classifies_plugin_credential_failure_as_sanitized_category(self):
        result = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            "",
            "getting credentials: invalid_grant access_token=do-not-print-this",
        )
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result),
            "gke-auth-plugin-credential-error",
        )
        lines = []
        DIAGNOSTICS.record_api_check(lines, "Kubernetes API probe", result)
        report = "\n".join(lines)
        self.assertIn("gke-auth-plugin-credential-error", report)
        self.assertNotIn("do-not-print-this", report)

    def test_reports_generic_plugin_execution_failure_separately(self):
        result = subprocess.CompletedProcess(
            ["kubectl"], 1, "", "exec plugin returned an unclassified failure"
        )
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result),
            "gke-auth-plugin-execution-error",
        )

    def test_report_records_only_sanitized_category_not_response_body(self):
        secret_like_body = "<!doctype html> session access_token=do-not-print-this"
        result = subprocess.CompletedProcess(["kubectl"], 1, "", secret_like_body)
        lines = []
        DIAGNOSTICS.record_api_check(lines, "Kubernetes API probe", result)
        report = "\n".join(lines)
        self.assertIn("google-dns-frontend-http-403", report)
        self.assertNotIn("do-not-print-this", report)

    def test_unexpected_kubeconfig_identity_is_not_reported_as_expected(self):
        self.assertEqual(
            DIAGNOSTICS.safe_identity("unexpected@example.test"),
            "unexpected@example.test",
        )
        self.assertEqual(
            DIAGNOSTICS.safe_identity("token\nwith-secret"),
            "<identity omitted: unexpected format>",
        )

    def test_adc_impersonation_config_identifies_only_expected_runner(self):
        expected_url = (
            "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
            + DIAGNOSTICS.EXPECTED_IDENTITY
            + ":generateAccessToken"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "adc.json")
            with open(path, "w", encoding="utf-8") as credential_file:
                json.dump({"service_account_impersonation_url": expected_url}, credential_file)
            self.assertEqual(
                DIAGNOSTICS.credential_impersonation_target_status(path), "expected"
            )

            wrong_path = os.path.join(directory, "wrong-adc.json")
            with open(wrong_path, "w", encoding="utf-8") as credential_file:
                json.dump(
                    {
                        "service_account_impersonation_url": expected_url.replace(
                            "helpdesk-app-migr-runner-dev", "other-runner"
                        )
                    },
                    credential_file,
                )
            self.assertEqual(
                DIAGNOSTICS.credential_impersonation_target_status(wrong_path),
                "unexpected",
            )

    def test_namespace_probes_do_not_request_cluster_scoped_namespace_object(self):
        commands = []

        def fake_kube_command(_kubeconfig, *args):
            commands.append(args)
            if args[:3] == ("auth", "whoami", "-o"):
                stdout = json.dumps(
                    {"status": {"userInfo": {"username": DIAGNOSTICS.EXPECTED_IDENTITY}}}
                )
            elif args[:2] == ("auth", "can-i"):
                stdout = "yes\n"
            else:
                stdout = "ok\n"
            return subprocess.CompletedProcess(["kubectl"], 0, stdout, "")

        original = DIAGNOSTICS.kube_command
        DIAGNOSTICS.kube_command = fake_kube_command
        try:
            lines = []
            DIAGNOSTICS.run_kubernetes_checks("unused", lines)
        finally:
            DIAGNOSTICS.kube_command = original

        self.assertNotIn(
            ("get", "namespace", DIAGNOSTICS.NAMESPACE, "-o", "name"), commands
        )
        self.assertTrue(
            any(
                command[:2] == ("get", "serviceaccount/helpdesk-dev-migrate")
                and "--namespace" in command
                and DIAGNOSTICS.NAMESPACE in command
                for command in commands
            )
        )
        self.assertIn("no cluster-scoped Namespace GET is attempted.", "\n".join(lines))

if __name__ == "__main__":
    unittest.main()
