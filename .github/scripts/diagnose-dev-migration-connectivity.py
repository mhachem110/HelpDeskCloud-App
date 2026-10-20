#!/usr/bin/env python3
"""Run sanitized, read-only checks for the protected Dev migration identity."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen


PROJECT = "helpdeskcloud-capstone-511905"
REGION = "us-east1"
CLUSTER = "helpdeskcloud-dev-gke"
NAMESPACE = "helpdesk-dev"
EXPECTED_IDENTITY = (
    "helpdesk-app-migr-runner-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com"
)
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
USERINFO_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
BOOTSTRAP_READS = (
    ("migration ServiceAccount", "serviceaccount", "helpdesk-dev-migrate"),
    ("admin SecretProviderClass", "secretproviderclass", "helpdesk-dev-db-admin"),
    ("migration ConfigMap", "configmap", "helpdesk-dev-schema-001"),
)
NAMESPACE_PERMISSIONS = (
    ("create jobs", "create", "jobs"),
    ("get jobs", "get", "jobs"),
    ("list jobs", "list", "jobs"),
    ("watch jobs", "watch", "jobs"),
    ("get pods", "get", "pods"),
    ("list pods", "list", "pods"),
    ("watch pods", "watch", "pods"),
    ("get pod logs", "get", "pods/log"),
    ("read migration ServiceAccount", "get", "serviceaccount/helpdesk-dev-migrate"),
    (
        "read admin SecretProviderClass",
        "get",
        "secretproviderclass/helpdesk-dev-db-admin",
    ),
    ("read migration ConfigMap", "get", "configmap/helpdesk-dev-schema-001"),
)


def run(
    command: list[str],
    *,
    kubeconfig: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Capture all command output; callers report only parsed, sanitized results."""
    environment = os.environ.copy()
    if kubeconfig is not None:
        environment["KUBECONFIG"] = kubeconfig
    if extra_env:
        environment.update(extra_env)
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", "[diagnostic:command-timeout]")
    except OSError:
        return subprocess.CompletedProcess(command, 127, "", "[diagnostic:executable-unavailable]")


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}".strip()


def classify_api_result(result: subprocess.CompletedProcess[str]) -> str:
    """Return a safe category instead of logging server response bodies."""
    output = _combined(result)
    lowered = output.lower()

    if "[diagnostic:command-timeout]" in lowered:
        return "diagnostic-command-timeout"
    if "[diagnostic:executable-unavailable]" in lowered:
        return "diagnostic-executable-unavailable"

    if any(
        marker in lowered
        for marker in (
            "<!doctype html",
            "<html",
            "google.com/images/errors/robot.png",
            "error 403 (forbidden)",
            "403. that’s an error",
            "403. that's an error",
        )
    ):
        return "google-dns-frontend-http-403"

    plugin_invocation = any(
        marker in lowered
        for marker in (
            "gke-gcloud-auth-plugin",
            "exec plugin",
            "auth provider",
            "getting credentials",
            "failed to get token",
        )
    )
    if plugin_invocation:
        if any(
            marker in lowered
            for marker in (
                "executable gke-gcloud-auth-plugin not found",
                "gke-gcloud-auth-plugin: command not found",
                "fork/exec gke-gcloud-auth-plugin",
                "exec: no such file or directory",
            )
        ):
            return "gke-auth-plugin-executable-unavailable"
        if any(
            marker in lowered
            for marker in (
                "failed to retrieve access token",
                "could not retrieve access token",
                "could not fetch access token",
                "oauth2: cannot fetch token",
                "invalid_grant",
                "invalid_rapt",
                "unauthorized_client",
                "service account impersonation",
            )
        ):
            return "gke-auth-plugin-credential-error"
        if any(
            marker in lowered
            for marker in (
                "no auth provider found for name gcp",
                "no auth provider found for name: gcp",
                "auth provider gcp is not supported",
            )
        ):
            return "legacy-gcp-auth-provider-unsupported"
        return "gke-auth-plugin-execution-error"

    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and (
        payload.get("reason") == "Forbidden"
        or (payload.get("kind") == "Status" and payload.get("code") == 403)
        or (payload.get("status") == "Failure" and payload.get("code") == 403)
    ):
        return "kubernetes-authorization-forbidden"
    if "error from server (forbidden)" in lowered or "forbidden:" in lowered:
        return "kubernetes-authorization-forbidden"
    if "unauthorized" in lowered or "provide credentials" in lowered:
        return "kubernetes-authentication-rejected"
    if any(marker in lowered for marker in ("no such host", "dns lookup", "name or service not known")):
        return "dns-resolution-failed"
    if any(marker in lowered for marker in ("timed out", "timeout", "i/o timeout")):
        return "endpoint-timeout"
    if result.returncode == 0:
        return "success"
    return "request-failed-details-suppressed"


def safe_identity(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9@._:/-]{1,254}", value):
        return value
    return "<identity omitted: unexpected format>"


def credential_impersonation_target_status(path: str) -> str:
    """Check the ADC impersonation target without exposing credential contents."""
    if not path or not os.path.isfile(path):
        return "unavailable"
    try:
        with open(path, encoding="utf-8") as credential_file:
            credentials = json.load(credential_file)
    except (OSError, json.JSONDecodeError):
        return "unavailable"
    if not isinstance(credentials, dict):
        return "unavailable"
    target = credentials.get("service_account_impersonation_url")
    if not isinstance(target, str):
        return "unavailable"
    match = re.fullmatch(
        r"https://iamcredentials\.googleapis\.com/v1/projects/[^/]+/serviceAccounts/([^/:]+):generateAccessToken",
        target,
    )
    if not match:
        return "unexpected"
    return "expected" if unquote(match.group(1)) == EXPECTED_IDENTITY else "unexpected"


def emit(lines: list[str]) -> None:
    method = os.environ.get("AUTH_METHOD", "unknown")
    report = [f"### {method}", ""] + [f"- {line}" for line in lines]
    for line in report:
        print(line)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("\n".join(report) + "\n")


def describe_cluster(lines: list[str]) -> tuple[dict | None, bool]:
    result = run(
        [
            "gcloud",
            "container",
            "clusters",
            "describe",
            CLUSTER,
            f"--project={PROJECT}",
            f"--location={REGION}",
            "--format=json",
        ]
    )
    if result.returncode != 0:
        lines.append("Google Cloud API authentication or GKE metadata lookup failed; response details suppressed.")
        return None, False
    try:
        cluster = json.loads(result.stdout)
    except json.JSONDecodeError:
        lines.append("Google Cloud API authentication succeeded, but GKE metadata was unreadable; details suppressed.")
        return None, False

    if not isinstance(cluster, dict):
        lines.append("GKE metadata lookup: returned an unexpected document; details suppressed.")
        return None, False
    lines.append("Google Cloud API authentication: successful read-only GKE metadata request.")
    control_plane = cluster.get("controlPlaneEndpointsConfig") or {}
    if not isinstance(control_plane, dict):
        lines.append("GKE endpoint metadata was malformed; details suppressed.")
        return None, False
    endpoint_config = control_plane.get("dnsEndpointConfig") or {}
    if not isinstance(endpoint_config, dict):
        lines.append("GKE DNS endpoint metadata was malformed; details suppressed.")
        return None, False
    endpoint_value = endpoint_config.get("endpoint", "")
    endpoint = endpoint_value if isinstance(endpoint_value, str) else ""
    allow_external_value = endpoint_config.get("allowExternalTraffic")
    ip_endpoints = control_plane.get("ipEndpointsConfig") or {}
    if not isinstance(ip_endpoints, dict):
        lines.append("GKE IP endpoint metadata was malformed; details suppressed.")
        return None, False
    ip_enabled = ip_endpoints.get("enabled")
    cluster_ok = (
        cluster.get("name") == CLUSTER
        and cluster.get("location", cluster.get("zone")) == REGION
        and re.fullmatch(r"[a-z0-9.-]+\.gke\.goog", endpoint) is not None
        and allow_external_value is True
        and ip_enabled is False
    )
    allow_external = (
        str(allow_external_value).lower()
        if isinstance(allow_external_value, bool)
        else "unknown"
    )
    ip_enabled_label = str(ip_enabled).lower() if isinstance(ip_enabled, bool) else "unknown"
    if endpoint:
        safe_endpoint = (
            endpoint
            if re.fullmatch(r"[a-z0-9.-]+\.gke\.goog", endpoint)
            else "<invalid DNS endpoint>"
        )
        safe_name = (
            cluster.get("name")
            if re.fullmatch(r"[A-Za-z0-9.-]{1,63}", str(cluster.get("name", "")))
            else "<unexpected>"
        )
        safe_location_value = cluster.get("location", cluster.get("zone", ""))
        safe_location = (
            safe_location_value
            if re.fullmatch(r"[a-z0-9-]{1,63}", str(safe_location_value))
            else "<unexpected>"
        )
        lines.append(
            f"GKE target: {safe_name} in {safe_location}; DNS endpoint {safe_endpoint}; "
            f"external traffic={allow_external}; IP endpoints enabled={ip_enabled_label}."
        )
    else:
        lines.append("GKE target: DNS endpoint missing; endpoint details suppressed.")
    lines.append(f"GKE metadata matches the expected Dev target: {'yes' if cluster_ok else 'NO'}.")
    return cluster, cluster_ok


def kube_command(kubeconfig: str, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["kubectl", "--kubeconfig", kubeconfig, *args], kubeconfig=kubeconfig)


def minified_kubeconfig(kubeconfig: str) -> tuple[dict | None, str]:
    """Read the selected kubeconfig without printing credential data."""
    result = kube_command(kubeconfig, "config", "view", "--raw", "--minify", "-o", "json")
    if result.returncode != 0:
        return None, "kubeconfig-unreadable"
    try:
        config = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "kubeconfig-malformed"
    if not isinstance(config, dict):
        return None, "kubeconfig-malformed"
    return config, "readable"


def kubeconfig_user_auth(config: dict) -> tuple[str | None, dict | None, str]:
    """Return the selected username and its auth object from a minified config."""
    contexts = config.get("contexts")
    users = config.get("users")
    if not isinstance(contexts, list) or len(contexts) != 1 or not isinstance(users, list):
        return None, None, "kubeconfig-auth-entry-missing"
    context = contexts[0]
    if not isinstance(context, dict):
        return None, None, "kubeconfig-auth-entry-missing"
    context_data = context.get("context")
    if not isinstance(context_data, dict):
        return None, None, "kubeconfig-auth-entry-missing"
    user_name = context_data.get("user")
    matching = [
        item
        for item in users
        if isinstance(item, dict) and item.get("name") == user_name
    ]
    if len(matching) != 1 or not isinstance(matching[0].get("user"), dict):
        return None, None, "kubeconfig-auth-entry-missing"
    return user_name, matching[0]["user"], "readable"


def introspect_access_token(token: str) -> dict | None:
    """Introspect a bearer token by POSTing it in the body; never expose it in a URL."""
    if not token:
        return None
    request = Request(
        TOKENINFO_URL,
        data=urlencode({"access_token": token}).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read(16 * 1024))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def token_identity_and_scope_status(payload: dict | None) -> tuple[str, bool]:
    """Return only a sanitized result for the exact token used by kubectl."""
    if not isinstance(payload, dict):
        return "token-introspection-unavailable", False
    identity_ok = payload.get("email") == EXPECTED_IDENTITY
    raw_scopes = payload.get("scope", "")
    scopes = set(raw_scopes.split()) if isinstance(raw_scopes, str) else set()
    cloud_scope_ok = CLOUD_PLATFORM_SCOPE in scopes
    email_scope_ok = USERINFO_EMAIL_SCOPE in scopes
    if not identity_ok:
        return "token-identity-unexpected", False
    if not cloud_scope_ok:
        return "token-cloud-platform-scope-missing", False
    if not email_scope_ok:
        return "token-userinfo-email-scope-missing", False
    return "expected", True


def prepare_api_kubeconfig(kubeconfig: str, lines: list[str]) -> tuple[bool, str | None, str | None]:
    """Validate the credential, returning a kubeconfig that presents that exact token."""
    config, read_status = minified_kubeconfig(kubeconfig)
    if config is None:
        lines.append(f"Kubeconfig credential entry: {read_status}.")
        return False, None, None
    user_name, auth, read_status = kubeconfig_user_auth(config)
    if auth is None:
        lines.append(f"Kubeconfig credential entry: {read_status}.")
        return False, None, None

    token = auth.get("token")
    if isinstance(token, str) and token:
        status, ok = token_identity_and_scope_status(introspect_access_token(token))
        lines.append(
            "Exact kubeconfig bearer token: service-account identity and required OAuth scopes "
            f"{'verified' if ok else status}."
        )
        return (True, kubeconfig, None) if ok else (False, None, None)

    exec_config = auth.get("exec")
    if isinstance(exec_config, dict):
        command = exec_config.get("command")
        args = exec_config.get("args", [])
        api_version = exec_config.get("apiVersion")
        plugin_ok = (
            command == "gke-gcloud-auth-plugin"
            and args == ["--use_application_default_credentials"]
            and api_version in {
                "client.authentication.k8s.io/v1",
                "client.authentication.k8s.io/v1beta1",
            }
        )
        if not plugin_ok:
            lines.append("Kubeconfig credential source is not the approved GKE exec plugin using ADC.")
            return False, None, None

        exec_info: dict = {
            "apiVersion": api_version,
            "kind": "ExecCredential",
            "spec": {"interactive": False},
        }
        if exec_config.get("provideClusterInfo") is True:
            clusters = config.get("clusters")
            context_data = config["contexts"][0].get("context", {})
            cluster_name = context_data.get("cluster") if isinstance(context_data, dict) else None
            cluster_entries = [
                item
                for item in clusters or []
                if isinstance(item, dict) and item.get("name") == cluster_name
            ]
            if len(cluster_entries) != 1 or not isinstance(cluster_entries[0].get("cluster"), dict):
                lines.append("GKE exec-plugin cluster context is incomplete; credential was not requested.")
                return False, None, None
            exec_info["spec"]["cluster"] = cluster_entries[0]["cluster"]

        result = run(
            [command, *args],
            kubeconfig=kubeconfig,
            extra_env={"KUBERNETES_EXEC_INFO": json.dumps(exec_info)},
        )
        if result.returncode != 0:
            lines.append(f"GKE exec-plugin credential request: {classify_api_result(result)}.")
            return False, None, None
        try:
            credential = json.loads(result.stdout)
            token = credential.get("status", {}).get("token")
        except (json.JSONDecodeError, AttributeError):
            token = None
            credential = None
        if (
            not isinstance(credential, dict)
            or credential.get("kind") != "ExecCredential"
            or credential.get("apiVersion") != api_version
            or not isinstance(token, str)
            or not token
        ):
            lines.append("GKE exec-plugin credential response was invalid; response details suppressed.")
            return False, None, None

        status, token_ok = token_identity_and_scope_status(introspect_access_token(token))
        lines.append(
            "Exact GKE exec-plugin token: service-account identity and required OAuth scopes "
            f"{'verified' if token_ok else status}."
        )
        if not token_ok:
            return False, None, None

        _, selected_auth, selected_status = kubeconfig_user_auth(config)
        if selected_auth is None or selected_status != "readable":
            lines.append("Kubeconfig auth entry could not be safely prepared for the API probes.")
            return False, None, None
        selected_auth.pop("exec", None)
        selected_auth.pop("auth-provider", None)
        selected_auth["token"] = token
        token_config_path: str | None = None
        try:
            descriptor, token_config_path = tempfile.mkstemp(
                prefix="helpdesk-gke-diagnostic-", suffix=".json"
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as token_config:
                json.dump(config, token_config)
        except OSError:
            if token_config_path:
                try:
                    os.unlink(token_config_path)
                except OSError:
                    pass
            lines.append("Could not create a protected temporary kubeconfig for read-only probes.")
            return False, None, None
        lines.append("GKE exec-plugin token will be used directly for the read-only Kubernetes probes.")
        return True, token_config_path, token_config_path

    if isinstance(auth.get("auth-provider"), dict):
        provider = auth["auth-provider"].get("name")
        if provider == "gcp":
            lines.append("Kubeconfig credential source is the unsupported legacy gcp auth-provider stanza.")
            return False, None, None
    lines.append("Kubeconfig credential source is neither a bearer token nor the supported GKE exec plugin.")
    return False, None, None


def verify_kubeconfig_credentials(kubeconfig: str, lines: list[str]) -> bool:
    """Convenience check used by tests; remove any temporary token-bearing config."""
    ok, _, cleanup_path = prepare_api_kubeconfig(kubeconfig, lines)
    if cleanup_path:
        try:
            os.unlink(cleanup_path)
        except OSError:
            return False
    return ok


def verify_kube_target(kubeconfig: str, cluster: dict | None, lines: list[str]) -> bool:
    if not cluster:
        lines.append("Kubernetes API checks skipped because the GKE target could not be verified.")
        return False
    expected_context = f"gke_{PROJECT}_{REGION}_{CLUSTER}"
    context = kube_command(kubeconfig, "config", "current-context")
    actual_context = context.stdout.strip() if context.returncode == 0 else ""
    context_ok = actual_context == expected_context
    lines.append(
        f"kubectl context matches expected cluster: {'yes' if context_ok else 'NO'}"
        + (f" ({safe_identity(actual_context)})" if actual_context else " (unavailable).")
    )

    server = kube_command(
        kubeconfig,
        "config",
        "view",
        "--minify",
        "-o",
        "jsonpath={.clusters[0].cluster.server}",
    )
    server_url = server.stdout.strip() if server.returncode == 0 else ""
    control_plane = cluster.get("controlPlaneEndpointsConfig") or {}
    expected_endpoint = (control_plane.get("dnsEndpointConfig") or {}).get("endpoint", "")
    if not isinstance(expected_endpoint, str):
        expected_endpoint = ""
    try:
        parsed_server = urlparse(server_url)
        hostname = parsed_server.hostname or ""
    except ValueError:
        parsed_server = None
        hostname = ""
    endpoint_ok = (
        server.returncode == 0
        and parsed_server is not None
        and parsed_server.scheme == "https"
        and hostname == expected_endpoint
    )
    lines.append(
        f"kubeconfig points to the verified DNS endpoint: {'yes' if endpoint_ok else 'NO'}"
        + (f" ({hostname})" if hostname else ".")
    )
    if not (context_ok and endpoint_ok):
        lines.append("Kubernetes API checks skipped to avoid querying an unverified target.")
        return False
    return True


def record_api_check(
    lines: list[str], label: str, result: subprocess.CompletedProcess[str], *, expected_identity: bool = False
) -> str:
    category = classify_api_result(result)
    if expected_identity:
        try:
            payload = json.loads(result.stdout)
            identity = payload.get("status", {}).get("userInfo", {}).get("username", "")
        except (json.JSONDecodeError, AttributeError):
            identity = ""
        if category == "success" and identity:
            matches = identity == EXPECTED_IDENTITY
            lines.append(
                f"Authenticated Kubernetes identity: {safe_identity(identity)} "
                f"({'expected' if matches else 'UNEXPECTED'})."
            )
            return "expected-identity" if matches else "unexpected-identity"
        lines.append(f"Authenticated Kubernetes identity check: {category}.")
        return category
    lines.append(f"{label}: {category}.")
    return category


def run_kubernetes_checks(kubeconfig: str, lines: list[str]) -> bool:
    checks_ok = True
    version = kube_command(kubeconfig, "get", "--raw=/version")
    version_category = record_api_check(lines, "Kubernetes API version probe", version)
    checks_ok = checks_ok and version_category == "success"

    identity = kube_command(kubeconfig, "auth", "whoami", "-o", "json")
    identity_status = record_api_check(lines, "Kubernetes identity", identity, expected_identity=True)
    checks_ok = checks_ok and identity_status == "expected-identity"

    lines.append(
        "Namespace scope is checked through helpdesk-dev namespaced object reads; "
        "no cluster-scoped Namespace GET is attempted."
    )

    for label, resource, name in BOOTSTRAP_READS:
        result = kube_command(kubeconfig, "get", f"{resource}/{name}", "--namespace", NAMESPACE, "-o", "name")
        category = record_api_check(lines, f"Existing {label}", result)
        checks_ok = checks_ok and category == "success"

    for label, verb, resource in NAMESPACE_PERMISSIONS:
        result = kube_command(
            kubeconfig,
            "auth",
            "can-i",
            verb,
            resource,
            "--namespace",
            NAMESPACE,
        )
        category = classify_api_result(result)
        answer = result.stdout.strip().lower()
        if answer in {"yes", "no"} and category == "success":
            lines.append(f"Namespace permission {label}: {answer}.")
            checks_ok = checks_ok and answer == "yes"
        else:
            lines.append(f"Namespace permission {label}: {category}.")
            checks_ok = False
    lines.append(f"Read-only Kubernetes connectivity and namespace checks: {'PASS' if checks_ok else 'FAIL'}.")
    return checks_ok


def main() -> int:
    kubeconfig = os.environ.get("KUBECONFIG_PATH", "")
    if not kubeconfig or not os.path.isfile(kubeconfig):
        print("Diagnostic stopped: the credential action did not provide a readable kubeconfig.")
        return 2

    lines: list[str] = []
    credential_status = credential_impersonation_target_status(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    )
    adc_identity_ok = credential_status == "expected"
    lines.append(
        "Google ADC credential configuration targets the expected migration-runner "
        f"service account: {'yes' if adc_identity_ok else credential_status}."
    )
    cluster, cluster_ok = describe_cluster(lines)
    target_ok = cluster_ok and verify_kube_target(kubeconfig, cluster, lines)
    credential_ok, api_kubeconfig, cleanup_path = prepare_api_kubeconfig(kubeconfig, lines)
    api_ok = False
    try:
        if target_ok and credential_ok and api_kubeconfig:
            api_ok = run_kubernetes_checks(api_kubeconfig, lines)
        elif not target_ok:
            lines.append("No Kubernetes API request was sent because target verification failed.")
        else:
            lines.append("No Kubernetes API request was sent because credential verification failed.")
    finally:
        if cleanup_path:
            try:
                os.unlink(cleanup_path)
            except OSError:
                lines.append("Temporary credential cleanup failed; inspect the runner workspace before reuse.")
                credential_ok = False
    lines.append("Diagnostic mode performs no Kubernetes writes and never runs migration SQL.")
    emit(lines)
    return 0 if adc_identity_ok and target_ok and credential_ok and api_ok else 1


if __name__ == "__main__":
    sys.exit(main())
