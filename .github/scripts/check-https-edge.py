"""Validate the separately managed HTTPS Gateway before a future edge rollout."""

import sys
from pathlib import Path

import yaml


EXPECTED = {
    "Gateway": ("gateway.networking.k8s.io/v1", "helpdesk-dev-https"),
    "HTTPRoute": ("gateway.networking.k8s.io/v1", "helpdesk-dev-https"),
    "GCPGatewayPolicy": ("networking.gke.io/v1", "helpdesk-dev-https-policy"),
    "GCPBackendPolicy": ("networking.gke.io/v1", "helpdesk-dev-iap"),
    "HealthCheckPolicy": ("networking.gke.io/v1", "helpdesk-dev-healthcheck"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_edge(documents, stage, hostname, certificate_map, static_ip, ssl_policy, oauth_client_id):
    require(stage in {"health-only", "application"}, "unknown edge stage")
    resources = [document for document in documents if document is not None]
    require(len(resources) == len(EXPECTED), "edge chart must render exactly the five reviewed resources")
    indexed = {}
    for resource in resources:
        require(isinstance(resource, dict), "invalid edge manifest document")
        kind = resource.get("kind")
        require(kind in EXPECTED and kind not in indexed, "unreviewed or duplicate edge resource")
        api_version, expected_name = EXPECTED[kind]
        metadata = resource.get("metadata", {})
        require(resource.get("apiVersion") == api_version, "unexpected edge API version")
        require(metadata.get("name") == expected_name and metadata.get("namespace") == "helpdesk-dev",
                "unexpected edge resource name or namespace")
        indexed[kind] = resource

    gateway = indexed["Gateway"]
    metadata = gateway["metadata"]
    require(metadata.get("annotations") == {"networking.gke.io/certmap": certificate_map},
            "Gateway must reference only the exact managed certificate map")
    spec = gateway.get("spec", {})
    require(spec.get("gatewayClassName") == "gke-l7-global-external-managed",
            "Gateway must use the reviewed global external managed class")
    require(spec.get("addresses") == [{"type": "NamedAddress", "value": static_ip}],
            "Gateway must use the retained named global IP")
    require(spec.get("listeners") == [{
        "name": "https", "protocol": "HTTPS", "port": 443,
        "allowedRoutes": {"namespaces": {"from": "Same"}},
        "tls": {"mode": "Terminate"},
    }], "Gateway must expose exactly one same-namespace HTTPS listener on 443")

    gateway_policy = indexed["GCPGatewayPolicy"].get("spec", {})
    require(gateway_policy == {
        "default": {"sslPolicy": ssl_policy},
        "targetRef": {"group": "gateway.networking.k8s.io", "kind": "Gateway", "name": "helpdesk-dev-https"},
    }, "Gateway must use the expected SSL policy")

    route = indexed["HTTPRoute"].get("spec", {})
    expected_path = {"type": "Exact", "value": "/health/live"} if stage == "health-only" else {
        "type": "PathPrefix", "value": "/"
    }
    require(route.get("parentRefs") == [{"name": "helpdesk-dev-https", "sectionName": "https"}],
            "HTTPRoute must attach only to the HTTPS listener")
    require(route.get("hostnames") == [hostname], "HTTPRoute must use only the owner-selected hostname")
    require(route.get("rules") == [{
        "matches": [{"path": expected_path}],
        "backendRefs": [{"name": "helpdesk-helpdesk", "port": 80}],
    }], "HTTPRoute path or backend is outside the reviewed scope")

    backend_policy = indexed["GCPBackendPolicy"].get("spec", {})
    require(backend_policy == {
        "default": {"iap": {
            "enabled": True,
            "oauth2ClientSecret": {"name": "helpdesk-iap-oauth"},
            "clientID": oauth_client_id,
        }},
        "targetRef": {"group": "", "kind": "Service", "name": "helpdesk-helpdesk"},
    }, "backend must use IAP and the fixed app Service and namespace secret")

    health_policy = indexed["HealthCheckPolicy"].get("spec", {})
    require(health_policy == {
        "default": {
            "checkIntervalSec": 15,
            "timeoutSec": 5,
            "healthyThreshold": 2,
            "unhealthyThreshold": 3,
            "config": {"type": "HTTP", "httpHealthCheck": {
                "portSpecification": "USE_FIXED_PORT", "port": 8080, "requestPath": "/health/live"
            }},
        },
        "targetRef": {"group": "", "kind": "Service", "name": "helpdesk-helpdesk"},
    }, "health checks must target the app's unauthenticated liveness endpoint on port 8080")


def main():
    if len(sys.argv) != 8:
        raise ValueError("usage: check-https-edge.py YAML STAGE HOSTNAME CERT_MAP STATIC_IP SSL_POLICY OAUTH_CLIENT_ID")
    _, manifest_path, stage, hostname, certificate_map, static_ip, ssl_policy, oauth_client_id = sys.argv
    with Path(manifest_path).open(encoding="utf-8") as source:
        check_edge(list(yaml.safe_load_all(source)), stage, hostname, certificate_map,
                   static_ip, ssl_policy, oauth_client_id)
    print(f"HTTPS edge {stage} scope verified: HTTPS only, exact hostname, IAP and app backend.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, yaml.YAMLError) as error:
        print(f"::error::HTTPS edge check failed: {error if isinstance(error, ValueError) else type(error).__name__}",
              file=sys.stderr)
        sys.exit(1)
