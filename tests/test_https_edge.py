import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".github" / "scripts" / "check-https-edge.py"
spec = importlib.util.spec_from_file_location("https_edge", SCRIPT)
edge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)


def manifests(stage="health-only"):
    path = {"type": "Exact", "value": "/health/live"} if stage == "health-only" else {
        "type": "PathPrefix", "value": "/"
    }
    return [
        {"apiVersion": "gateway.networking.k8s.io/v1", "kind": "Gateway", "metadata": {
            "name": "helpdesk-dev-https", "namespace": "helpdesk-dev",
            "annotations": {"networking.gke.io/certmap": "helpdesk-cert-map"}},
         "spec": {"gatewayClassName": "gke-l7-global-external-managed",
                  "addresses": [{"type": "NamedAddress", "value": "helpdesk-https-ip"}],
                  "listeners": [{"name": "https", "protocol": "HTTPS", "port": 443,
                                 "allowedRoutes": {"namespaces": {"from": "Same"}},
                                 "tls": {"mode": "Terminate"}}]}},
        {"apiVersion": "networking.gke.io/v1", "kind": "GCPGatewayPolicy",
         "metadata": {"name": "helpdesk-dev-https-policy", "namespace": "helpdesk-dev"},
         "spec": {"default": {"sslPolicy": "helpdesk-tls"}, "targetRef": {
             "group": "gateway.networking.k8s.io", "kind": "Gateway", "name": "helpdesk-dev-https"}}},
        {"apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute",
         "metadata": {"name": "helpdesk-dev-https", "namespace": "helpdesk-dev"},
         "spec": {"parentRefs": [{"name": "helpdesk-dev-https", "sectionName": "https"}],
                  "hostnames": ["dev.example.com"], "rules": [{"matches": [{"path": path}],
                  "backendRefs": [{"name": "helpdesk-helpdesk", "port": 80}]}]}},
        {"apiVersion": "networking.gke.io/v1", "kind": "GCPBackendPolicy",
         "metadata": {"name": "helpdesk-dev-iap", "namespace": "helpdesk-dev"},
         "spec": {"default": {"iap": {"enabled": True,
             "oauth2ClientSecret": {"name": "helpdesk-iap-oauth"},
             "clientID": "123456789012-abc.apps.googleusercontent.com"}},
             "targetRef": {"group": "", "kind": "Service", "name": "helpdesk-helpdesk"}}},
        {"apiVersion": "networking.gke.io/v1", "kind": "HealthCheckPolicy",
         "metadata": {"name": "helpdesk-dev-healthcheck", "namespace": "helpdesk-dev"},
         "spec": {"default": {"checkIntervalSec": 15, "timeoutSec": 5, "healthyThreshold": 2,
             "unhealthyThreshold": 3, "config": {"type": "HTTP", "httpHealthCheck": {
                 "portSpecification": "USE_FIXED_PORT", "port": 8080, "requestPath": "/health/live"}}},
             "targetRef": {"group": "", "kind": "Service", "name": "helpdesk-helpdesk"}}},
    ]


class HttpsEdgeGuardTests(unittest.TestCase):
    def check(self, docs, stage="health-only"):
        edge.check_edge(docs, stage, "dev.example.com", "helpdesk-cert-map", "helpdesk-https-ip",
                        "helpdesk-tls", "123456789012-abc.apps.googleusercontent.com")

    def test_health_only_route_is_exact_liveness_path(self):
        self.check(manifests())

    def test_application_route_is_single_root_prefix(self):
        self.check(manifests("application"), "application")

    def test_rejects_public_http_listener(self):
        docs = manifests()
        docs[0]["spec"]["listeners"].append({"name": "http", "protocol": "HTTP", "port": 80})
        with self.assertRaises(ValueError):
            self.check(docs)

    def test_rejects_health_route_expansion(self):
        docs = manifests()
        docs[2]["spec"]["rules"][0]["matches"][0]["path"] = {"type": "PathPrefix", "value": "/"}
        with self.assertRaises(ValueError):
            self.check(docs)

    def test_rejects_disabled_iap(self):
        docs = manifests()
        docs[3]["spec"]["default"]["iap"]["enabled"] = False
        with self.assertRaises(ValueError):
            self.check(docs)

    def test_rejects_unrelated_backend(self):
        docs = manifests()
        docs[2]["spec"]["rules"][0]["backendRefs"][0]["name"] = "other-service"
        with self.assertRaises(ValueError):
            self.check(docs)

    def test_rejects_unreviewed_resources(self):
        docs = manifests()
        docs.append({"apiVersion": "v1", "kind": "Service", "metadata": {"name": "public"}})
        with self.assertRaises(ValueError):
            self.check(docs)


if __name__ == "__main__":
    unittest.main()
