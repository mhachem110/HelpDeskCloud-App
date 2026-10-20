"""Prevent the app delivery path from accidentally exposing the ticket API."""

import copy
import importlib.util
import unittest

import yaml

from test_gke_manifests import CHART, ROOT, render


module_spec = importlib.util.spec_from_file_location(
    "private_release", ROOT / ".github/scripts/check-private-release.py")
policy = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(policy)


class PrivateReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release = render("-f", str(CHART / "values-dev-delivery.yaml"))

    def test_current_digest_pinned_delivery_passes(self):
        policy.check_release(self.release)

    def test_routing_resources_cannot_enter_the_app_release(self):
        for kind, api in (("Ingress", "networking.k8s.io/v1"),
                          ("Gateway", "gateway.networking.k8s.io/v1"),
                          ("HTTPRoute", "gateway.networking.k8s.io/v1"),
                          ("GCPBackendPolicy", "networking.gke.io/v1"),
                          ("Secret", "v1"), ("List", "v1")):
            added = {"apiVersion": api, "kind": kind, "metadata": {"name": "unapproved"}}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                policy.check_release(self.release + [added])

    def test_public_service_and_proxy_port_bypasses_are_rejected(self):
        mutations = (
            lambda s: s["spec"].update(type="LoadBalancer"),
            lambda s: s["spec"].update(type="NodePort"),
            lambda s: s["spec"].update(externalIPs=["203.0.113.10"]),
            lambda s: s["spec"].update(externalName="unapproved.invalid"),
            lambda s: s["spec"]["ports"].append({"port": 5432, "targetPort": 5432}),
            lambda s: s["spec"]["ports"][0].update(nodePort=30080),
            lambda s: s["metadata"].update(annotations={"cloud.google.com/backend-config": "unapproved"}),
            lambda s: s["spec"].update(selector={"app": "another-backend"}),
        )
        for mutate in mutations:
            release = copy.deepcopy(self.release)
            mutate(next(r for r in release if r["kind"] == "Service"))
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                policy.check_release(release)

    def test_host_network_bypasses_are_rejected(self):
        for field in ("network", "port"):
            release = copy.deepcopy(self.release)
            pod = next(r for r in release if r["kind"] == "Deployment")["spec"]["template"]["spec"]
            if field == "network":
                pod["hostNetwork"] = True
            else:
                pod["containers"][0]["ports"][0]["hostPort"] = 8080
            with self.subTest(field=field), self.assertRaises(ValueError):
                policy.check_release(release)

    def test_ci_and_protected_delivery_check_scope_before_kubernetes_writes(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/app-dev-delivery.yml").read_text())
        deploy_steps = workflow["jobs"]["deploy"]["steps"]
        render_step = next(step for step in deploy_steps
                           if step.get("name") == "Render and validate exact digest-pinned release")
        check = "python .github/scripts/check-private-release.py"
        self.assertLess(render_step["run"].index(check),
                        render_step["run"].index("kubectl apply --dry-run=server"))
        render_index = deploy_steps.index(render_step)
        upgrade_index = next(i for i, step in enumerate(deploy_steps)
                             if "helm upgrade --install" in step.get("run", ""))
        self.assertLess(render_index, upgrade_index)
        ci = yaml.safe_load((ROOT / ".github/workflows/app-ci.yml").read_text())
        self.assertTrue(any(check in step.get("run", "")
                            for step in ci["jobs"]["helm"]["steps"]))


if __name__ == "__main__":
    unittest.main()
