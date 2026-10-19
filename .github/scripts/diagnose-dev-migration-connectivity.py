#!/usr/bin/env python3
"""Run sanitized, read-only checks for the protected Dev migration identity."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from urllib.parse import unquote, urlparse


PROJECT = "helpdeskcloud-capstone-511905"
REGION = "us-east1"
CLUSTER = "helpdeskcloud-dev-gke"
NAMESPACE = "helpdesk-dev"
EXPECTED_IDENTITY = (
    "helpdesk-app-migr-runner-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com"
)
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


def run(command: list[str], *, kubeconfig: str | None = None) -> subprocess.CompletedProcess[str]:
    """Capture all command output; callers report only parsed, sanitized results."""
    environment = os.environ.copy()
    if kubeconfig is not None:
        environment["KUBECONFIG"] = kubeconfig
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


def run_kubernetes_checks(kubeconfig: str, lines: list[str]) -> None:
    version = kube_command(kubeconfig, "get", "--raw=/version")
    record_api_check(lines, "Kubernetes API version probe", version)

    identity = kube_command(kubeconfig, "auth", "whoami", "-o", "json")
    record_api_check(lines, "Kubernetes identity", identity, expected_identity=True)

    lines.append(
        "Namespace scope is checked through helpdesk-dev namespaced object reads; "
        "no cluster-scoped Namespace GET is attempted."
    )

    for label, resource, name in BOOTSTRAP_READS:
        result = kube_command(kubeconfig, "get", f"{resource}/{name}", "--namespace", NAMESPACE, "-o", "name")
        record_api_check(lines, f"Existing {label}", result)

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
        if answer in {"yes", "no"} and category not in {
            "google-dns-frontend-http-403",
            "kubernetes-authorization-forbidden",
            "kubernetes-authentication-rejected",
            "dns-resolution-failed",
            "endpoint-timeout",
        }:
            lines.append(f"Namespace permission {label}: {answer}.")
        else:
            lines.append(f"Namespace permission {label}: {category}.")


def main() -> int:
    kubeconfig = os.environ.get("KUBECONFIG_PATH", "")
    if not kubeconfig or not os.path.isfile(kubeconfig):
        print("Diagnostic stopped: the credential action did not provide a readable kubeconfig.")
        return 2

    lines: list[str] = []
    credential_status = credential_impersonation_target_status(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    )
    lines.append(
        "Google ADC credential configuration targets the expected migration-runner "
        f"service account: {'yes' if credential_status == 'expected' else credential_status}."
    )
    cluster, cluster_ok = describe_cluster(lines)
    if cluster_ok and verify_kube_target(kubeconfig, cluster, lines):
        run_kubernetes_checks(kubeconfig, lines)
    else:
        lines.append("No Kubernetes API request was sent because target verification failed.")
    lines.append("Diagnostic mode performs no Kubernetes writes and never runs migration SQL.")
    emit(lines)
    # API failures are the diagnostic subject. Complete both credential-mode checks and
    # report sanitized findings; fail only when inputs/tooling prevent safe diagnostics.
    return 0


if __name__ == "__main__":
    sys.exit(main())
