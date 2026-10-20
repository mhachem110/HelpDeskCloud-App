"""Reject exposure or platform resources in the application delivery manifest.

The edge access stack has a separate owner and approval lifecycle. This check is
offline: it reads rendered YAML and never contacts Kubernetes or Google Cloud.
"""

import re
import sys
from pathlib import Path

import yaml


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_release(documents):
    resources = [document for document in documents if document is not None]
    require(len(resources) == 2, "delivery must contain exactly one Deployment and one Service")
    indexed = {}
    for resource in resources:
        require(isinstance(resource, dict), "invalid manifest document")
        kind = resource.get("kind")
        require(kind in {"Deployment", "Service"} and kind not in indexed,
                "routing, IAM, bootstrap and additional resources require separate platform approval")
        expected_api = "apps/v1" if kind == "Deployment" else "v1"
        require(resource.get("apiVersion") == expected_api, "unexpected resource API")
        metadata = resource.get("metadata", {})
        require(metadata.get("name") == "helpdesk-helpdesk", "unexpected application resource name")
        require(metadata.get("namespace", "helpdesk-dev") == "helpdesk-dev", "unexpected namespace")
        indexed[kind] = resource

    service = indexed["Service"]
    spec = service.get("spec", {})
    require(spec.get("type") == "ClusterIP", "application Service must remain ClusterIP")
    require(not any(key in spec for key in
                    ("externalIPs", "externalName", "loadBalancerIP", "loadBalancerClass")),
            "external Service addressing requires separate platform approval")
    require(spec.get("selector") == {
        "app.kubernetes.io/name": "helpdesk", "app.kubernetes.io/instance": "helpdesk"},
        "Service must select only the existing application Pods")
    require(spec.get("ports") == [{"name": "http", "port": 80, "targetPort": 8080, "protocol": "TCP"}],
            "Service must expose only application HTTP inside the cluster")
    annotations = service.get("metadata", {}).get("annotations") or {}
    require(not any(key.startswith(("cloud.google.com/", "networking.gke.io/",
                                    "service.beta.kubernetes.io/", "ingress.kubernetes.io/"))
                    for key in annotations), "edge annotations belong to the platform access stack")

    deployment = indexed["Deployment"].get("spec", {})
    require(deployment.get("replicas") == 2, "delivery requires two application replicas")
    pod = deployment.get("template", {}).get("spec", {})
    require(not pod.get("hostNetwork", False), "application must not use host networking")
    for container in pod.get("containers", []) + pod.get("initContainers", []):
        require(not any("hostPort" in port for port in container.get("ports", [])),
                "application must not publish host ports")
    app_containers = [container for container in pod.get("containers", []) if container.get("name") == "helpdesk"]
    require(len(app_containers) == 1, "delivery must contain exactly one HelpDesk application container")
    app_env = {item.get("name"): item.get("value") for item in app_containers[0].get("env", [])}
    require(app_env.get("Iap__Enabled") in {"true", "false"}, "IAP enforcement must be an explicit boolean")
    if app_env["Iap__Enabled"] == "true":
        require(re.fullmatch(r"/projects/260283083469/global/backendServices/[0-9]+",
                             app_env.get("Iap__ExpectedAudience", "")) is not None,
                "IAP must use the exact Google project and numeric backend service audience")
        require(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", app_env.get("Iap__AllowedEmail", "")) is not None,
                "IAP must allow exactly one configured email address")
    else:
        require("Iap__ExpectedAudience" not in app_env and "Iap__AllowedEmail" not in app_env,
                "IAP identity values must not be rendered while enforcement is disabled")


def main():
    if len(sys.argv) != 2:
        raise ValueError("usage: check-private-release.py RENDERED_YAML")
    with Path(sys.argv[1]).open(encoding="utf-8") as source:
        check_release(list(yaml.safe_load_all(source)))
    print("Private application release scope verified; edge resources require separate approval.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, yaml.YAMLError) as error:
        # Manifest contents can include credentials. Print only our policy messages.
        print(f"::error::Private release check failed: {error if isinstance(error, ValueError) else type(error).__name__}",
              file=sys.stderr)
        sys.exit(1)
