"""Regression tests for sanitized GKE migration connectivity diagnostics."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse


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

    def test_classifies_removed_legacy_gcp_auth_provider(self):
        result = subprocess.CompletedProcess(
            ["kubectl"],
            1,
            "",
            "no Auth Provider found for name gcp",
        )
        self.assertEqual(
            DIAGNOSTICS.classify_api_result(result),
            "legacy-gcp-auth-provider-unsupported",
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

    def test_tokeninfo_requires_expected_service_account_and_scopes(self):
        valid = {
            "email": DIAGNOSTICS.EXPECTED_IDENTITY,
            "scope": (
                f"{DIAGNOSTICS.CLOUD_PLATFORM_SCOPE} "
                f"{DIAGNOSTICS.USERINFO_EMAIL_SCOPE}"
            ),
        }
        self.assertEqual(DIAGNOSTICS.token_identity_and_scope_status(valid), ("expected", True))
        self.assertEqual(
            DIAGNOSTICS.token_identity_and_scope_status(
                {**valid, "email": "other@example.test"}
            ),
            ("token-identity-unexpected", False),
        )
        self.assertEqual(
            DIAGNOSTICS.token_identity_and_scope_status(
                {**valid, "scope": DIAGNOSTICS.USERINFO_EMAIL_SCOPE}
            ),
            ("token-cloud-platform-scope-missing", False),
        )
        self.assertEqual(
            DIAGNOSTICS.token_identity_and_scope_status(
                {**valid, "scope": DIAGNOSTICS.CLOUD_PLATFORM_SCOPE}
            ),
            ("token-userinfo-email-scope-missing", False),
        )

    def test_tokeninfo_posts_token_in_body_and_never_in_url(self):
        token = "sensitive-test-token"
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "email": DIAGNOSTICS.EXPECTED_IDENTITY,
                "scope": f"{DIAGNOSTICS.CLOUD_PLATFORM_SCOPE} {DIAGNOSTICS.USERINFO_EMAIL_SCOPE}",
            }
        ).encode()
        with mock.patch.object(DIAGNOSTICS, "urlopen", return_value=response) as open_url:
            payload = DIAGNOSTICS.introspect_access_token(token)

        request = open_url.call_args.args[0]
        self.assertEqual(urlparse(request.full_url).query, "")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            parse_qs(request.data.decode())["access_token"],
            [token],
        )
        self.assertEqual(payload["email"], DIAGNOSTICS.EXPECTED_IDENTITY)

    def test_token_identity_report_does_not_echo_token_or_tokeninfo_payload(self):
        token = "sensitive-test-token"
        config = {
            "contexts": [{"name": "context", "context": {"user": "runner"}}],
            "users": [{"name": "runner", "user": {"token": token}}],
        }
        with (
            mock.patch.object(DIAGNOSTICS, "minified_kubeconfig", return_value=(config, "readable")),
            mock.patch.object(
                DIAGNOSTICS,
                "introspect_access_token",
                return_value={
                    "email": DIAGNOSTICS.EXPECTED_IDENTITY,
                    "scope": f"{DIAGNOSTICS.CLOUD_PLATFORM_SCOPE} {DIAGNOSTICS.USERINFO_EMAIL_SCOPE}",
                    "access_token": token,
                },
            ),
        ):
            lines = []
            self.assertTrue(DIAGNOSTICS.verify_kubeconfig_credentials("unused", lines))
        self.assertNotIn(token, "\n".join(lines))
        self.assertNotIn("access_token", "\n".join(lines))

    def test_plugin_kubeconfig_requires_exec_plugin_and_adc_flag(self):
        config = {
            "current-context": "context",
            "contexts": [{"name": "context", "context": {"user": "runner", "cluster": "dev"}}],
            "clusters": [{"name": "dev", "cluster": {"server": "https://dev.gke.goog"}}],
            "users": [{
                "name": "runner",
                "user": {
                    "exec": {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "command": "gke-gcloud-auth-plugin",
                        "args": ["--use_application_default_credentials"],
                        "provideClusterInfo": True,
                    }
                },
            }],
        }
        plugin_token = "plugin-test-token"
        plugin_response = json.dumps({
            "apiVersion": "client.authentication.k8s.io/v1beta1",
            "kind": "ExecCredential",
            "status": {"token": plugin_token},
        })
        with (
            mock.patch.object(DIAGNOSTICS, "minified_kubeconfig", return_value=(config, "readable")),
            mock.patch.object(
                DIAGNOSTICS,
                "run",
                return_value=subprocess.CompletedProcess(["gke-gcloud-auth-plugin"], 0, plugin_response, ""),
            ) as run_plugin,
            mock.patch.object(
                DIAGNOSTICS,
                "introspect_access_token",
                return_value={
                    "email": DIAGNOSTICS.EXPECTED_IDENTITY,
                    "scope": f"{DIAGNOSTICS.CLOUD_PLATFORM_SCOPE} {DIAGNOSTICS.USERINFO_EMAIL_SCOPE}",
                },
            ) as inspect_token,
        ):
            lines = []
            ok, token_config_path, cleanup_path = DIAGNOSTICS.prepare_api_kubeconfig("unused", lines)
            self.assertTrue(ok)
            self.assertEqual(token_config_path, cleanup_path)
            with open(token_config_path, encoding="utf-8") as token_config:
                prepared = json.load(token_config)
            self.assertEqual(prepared["users"][0]["user"]["token"], plugin_token)
            self.assertNotIn("exec", prepared["users"][0]["user"])
            exec_info = json.loads(run_plugin.call_args.kwargs["extra_env"]["KUBERNETES_EXEC_INFO"])
            self.assertEqual(exec_info["spec"]["cluster"]["server"], "https://dev.gke.goog")
            self.assertEqual(inspect_token.call_args.args, (plugin_token,))
            os.unlink(cleanup_path)

        legacy_config = {
            "contexts": [{"name": "context", "context": {"user": "runner"}}],
            "users": [{"name": "runner", "user": {"auth-provider": {"name": "gcp"}}}],
        }
        with mock.patch.object(
            DIAGNOSTICS,
            "minified_kubeconfig",
            return_value=(legacy_config, "readable"),
        ):
            legacy_lines = []
            self.assertFalse(DIAGNOSTICS.verify_kubeconfig_credentials("unused", legacy_lines))
        self.assertIn("unsupported legacy gcp auth-provider", "\n".join(legacy_lines))

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
            self.assertTrue(DIAGNOSTICS.run_kubernetes_checks("unused", lines))
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

    def test_kubernetes_connectivity_failures_return_failure(self):
        original = DIAGNOSTICS.kube_command

        def denied_kube_command(_kubeconfig, *args):
            if args[:2] == ("get", "--raw=/version"):
                return subprocess.CompletedProcess(
                    ["kubectl"], 1, "", "<!doctype html><title>403 Forbidden</title>"
                )
            if args[:3] == ("auth", "whoami", "-o"):
                return subprocess.CompletedProcess(["kubectl"], 1, "", "403 Forbidden")
            return subprocess.CompletedProcess(["kubectl"], 1, "", "403 Forbidden")

        DIAGNOSTICS.kube_command = denied_kube_command
        try:
            lines = []
            self.assertFalse(DIAGNOSTICS.run_kubernetes_checks("unused", lines))
        finally:
            DIAGNOSTICS.kube_command = original
        self.assertIn("Read-only Kubernetes connectivity and namespace checks: FAIL.", "\n".join(lines))

    def test_main_exits_nonzero_when_verified_target_still_cannot_connect(self):
        with (
            mock.patch.dict(
                os.environ,
                {
                    "KUBECONFIG_PATH": "unused-kubeconfig",
                    "GOOGLE_APPLICATION_CREDENTIALS": "unused-adc",
                },
            ),
            mock.patch.object(DIAGNOSTICS.os.path, "isfile", return_value=True),
            mock.patch.object(DIAGNOSTICS, "credential_impersonation_target_status", return_value="expected"),
            mock.patch.object(DIAGNOSTICS, "describe_cluster", return_value=({"name": "verified"}, True)),
            mock.patch.object(DIAGNOSTICS, "verify_kube_target", return_value=True),
            mock.patch.object(DIAGNOSTICS, "prepare_api_kubeconfig", return_value=(True, "unused-kubeconfig", None)),
            mock.patch.object(DIAGNOSTICS, "run_kubernetes_checks", return_value=False),
            mock.patch.object(DIAGNOSTICS, "emit"),
        ):
            self.assertEqual(DIAGNOSTICS.main(), 1)

if __name__ == "__main__":
    unittest.main()
