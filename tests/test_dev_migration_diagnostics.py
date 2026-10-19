"""Regression tests for sanitized GKE migration connectivity diagnostics."""

import importlib.util
import subprocess
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

if __name__ == "__main__":
    unittest.main()
