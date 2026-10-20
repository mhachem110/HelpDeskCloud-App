"""Check the rendered Dev chart without a Kubernetes cluster or credentials."""

import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "helm" / "helpdesk"
DEV_VALUES = CHART / "values-dev.yaml"
DIGESTS = [
    f"image.digest=sha256:{'a' * 64}",
    f"cloudSqlProxy.image.digest=sha256:{'b' * 64}",
    f"migration.image.digest=sha256:{'c' * 64}",
]


def render(*options):
    command = ["helm", "template", "helpdesk", str(CHART), "--namespace", "helpdesk-dev",
               "-f", str(DEV_VALUES)]
    for setting in DIGESTS:
        command.extend(["--set", setting])
    command.extend(options)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr)
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def one(manifests, kind):
    matched = [item for item in manifests if item["kind"] == kind]
    if len(matched) != 1:
        raise AssertionError(f"Expected one {kind}, found {len(matched)}")
    return matched[0]


class GkeManifestTests(unittest.TestCase):
    def test_runtime_is_private_and_uses_expected_identities(self):
        manifests = render()
        service = one(manifests, "Service")
        self.assertEqual(service["spec"]["type"], "ClusterIP")
        self.assertFalse(any(item["kind"] == "Ingress" for item in manifests))
        deployment = one(manifests, "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertEqual(pod["serviceAccountName"], "helpdesk-dev-app")
        self.assertEqual(deployment["spec"]["replicas"], 2)
        self.assertEqual([container["name"] for container in deployment["spec"]["template"]["spec"]["containers"]],
                         ["helpdesk", "cloud-sql-proxy"])
        self.assertEqual({container["name"] for container in pod["containers"]},
                         {"helpdesk", "cloud-sql-proxy"})
        for container in pod["containers"]:
            self.assertIn("@sha256:", container["image"])
            self.assertIn("cpu", container["resources"]["requests"])
            self.assertIn("memory", container["resources"]["limits"])
            self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
            self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        app, proxy = pod["containers"]
        self.assertEqual({p["path"] for p in (app["livenessProbe"]["httpGet"],
                                               app["readinessProbe"]["httpGet"])},
                         {"/health/live", "/health/ready"})
        self.assertIn("--private-ip", proxy["args"])
        self.assertIn("--address=127.0.0.1", proxy["args"])
        self.assertEqual(proxy["args"][-1],
                         "helpdeskcloud-capstone-511905:us-east1:helpdeskcloud-dev-postgres")
        self.assertEqual(pod["volumes"][0]["csi"]["driver"], "secrets-store-gke.csi.k8s.io")
        self.assertTrue(pod["volumes"][0]["csi"]["readOnly"])

    def test_managed_secret_mount_and_no_payload_in_manifests(self):
        manifests = render()
        providers = [item for item in manifests if item["kind"] == "SecretProviderClass"]
        self.assertEqual(len(providers), 2)
        self.assertEqual({item["spec"]["provider"] for item in providers}, {"gke"})
        self.assertIn("projects/helpdeskcloud-capstone-511905/secrets/helpdesk-dev-db-connection/versions/latest",
                      providers[0]["spec"]["parameters"]["secrets"])
        self.assertFalse(any(item["kind"] == "Secret" for item in manifests))
        accounts = {item["metadata"]["name"]: item for item in manifests if item["kind"] == "ServiceAccount"}
        self.assertEqual(accounts["helpdesk-dev-app"]["metadata"]["annotations"]["iam.gke.io/gcp-service-account"],
                         "helpdesk-app-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com")
        self.assertEqual(accounts["helpdesk-dev-migrate"]["metadata"]["annotations"]["iam.gke.io/gcp-service-account"],
                         "helpdesk-migrate-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com")

    def test_migration_job_is_manual_and_completes_with_native_sidecar(self):
        self.assertFalse(any(item["kind"] == "Job" for item in render()))
        manifests = render("--set", "application.enabled=false", "--set", "migration.enabled=true")
        self.assertFalse(any(item["kind"] in ("Service", "Deployment") for item in manifests))
        job = one(manifests, "Job")["spec"]["template"]["spec"]
        self.assertEqual(job["serviceAccountName"], "helpdesk-dev-migrate")
        self.assertEqual(job["restartPolicy"], "Never")
        sidecar = job["initContainers"][0]
        self.assertEqual(sidecar["restartPolicy"], "Always")
        self.assertIn("--private-ip", sidecar["args"])
        self.assertIn("--address=127.0.0.1", sidecar["args"])
        self.assertNotIn("--address=0.0.0.0", sidecar["args"])
        self.assertIn("--health-check", sidecar["args"])
        self.assertIn("--http-address=0.0.0.0", sidecar["args"])
        self.assertIn("--http-port=9801", sidecar["args"])
        self.assertEqual(sidecar["ports"], [{"name": "health", "containerPort": 9801, "protocol": "TCP"}])
        self.assertEqual(sidecar["startupProbe"]["httpGet"],
                         {"path": "/startup", "port": "health", "scheme": "HTTP"})
        self.assertEqual(sidecar["startupProbe"]["periodSeconds"], 5)
        self.assertEqual(sidecar["startupProbe"]["failureThreshold"], 30)
        self.assertIn("@sha256:", sidecar["image"])
        self.assertIn("@sha256:", job["containers"][0]["image"])
        self.assertEqual(job["volumes"][0]["csi"]["driver"], "secrets-store-gke.csi.k8s.io")
        config = one(manifests, "ConfigMap")["data"]
        self.assertEqual(config["001_init.sql"].strip(), (ROOT / "database" / "init.sql").read_text().strip())
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE", config["002_grants.sql"])

    def test_dev_requires_real_digests_and_rejects_public_service(self):
        for options in (("--set", "image.digest="), ("--set", "cloudSqlProxy.image.digest="),
                        ("--set", "service.type=LoadBalancer"), ("--set", "service.type=NodePort"),
                        ("--set", "migration.enabled=true")):
            with self.subTest(options=options), self.assertRaises(ValueError):
                render(*options)

    def test_delivery_release_cannot_change_bootstrap_identities_or_sql(self):
        manifests = render("-f", str(CHART / "values-dev-delivery.yaml"))
        self.assertEqual({item["kind"] for item in manifests}, {"Deployment", "Service"})
        deployment = one(manifests, "Deployment")
        self.assertEqual(deployment["spec"]["replicas"], 2)
        self.assertEqual(deployment["spec"]["template"]["spec"]["serviceAccountName"],
                         "helpdesk-dev-app")
        self.assertEqual(one(manifests, "Service")["spec"]["type"], "ClusterIP")


if __name__ == "__main__":
    unittest.main()
