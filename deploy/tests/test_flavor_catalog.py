import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[1]


class FlavorCatalogDeploymentTest(unittest.TestCase):
    def test_manifest_is_internal_ha_and_immutable_at_render_boundary(self):
        docs = list(yaml.safe_load_all((ROOT / "manifests/flavor-catalog.yaml").read_text()))
        deployment = next(x for x in docs if x["kind"] == "Deployment")
        service = next(x for x in docs if x["kind"] == "Service")
        policy = next(x for x in docs if x["kind"] == "NetworkPolicy")
        self.assertEqual(2, deployment["spec"]["replicas"])
        self.assertEqual(
            "RuntimeDefault",
            deployment["spec"]["template"]["spec"]["securityContext"]["seccompProfile"]["type"],
        )
        spread = deployment["spec"]["template"]["spec"]["topologySpreadConstraints"][0]
        self.assertEqual("kubernetes.io/hostname", spread["topologyKey"])
        self.assertEqual("DoNotSchedule", spread["whenUnsatisfiable"])
        self.assertEqual("FLAVOR_CATALOG_IMAGE", deployment["spec"]["template"]["spec"]["containers"][0]["image"])
        self.assertEqual("/tmp", deployment["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][0]["mountPath"])
        self.assertEqual("runtime", deployment["spec"]["template"]["spec"]["volumes"][0]["name"])
        self.assertEqual("ClusterIP", service["spec"].get("type", "ClusterIP"))
        self.assertEqual(["Ingress", "Egress"], policy["spec"]["policyTypes"])
        self.assertNotIn("HTTPRoute", [x["kind"] for x in docs])

    def test_only_horizon_can_reach_the_api(self):
        policy = list(yaml.safe_load_all((ROOT / "manifests/flavor-catalog.yaml").read_text()))[-1]
        source = policy["spec"]["ingress"][0]["from"][0]
        self.assertEqual("horizon", source["podSelector"]["matchLabels"]["application"])

    def test_isolated_horizon_peer_requires_both_exact_namespace_and_pod(self):
        policy = list(yaml.safe_load_all((ROOT / "manifests/flavor-catalog.yaml").read_text()))[-1]
        rules = policy["spec"]["ingress"]
        self.assertEqual(2, len(rules))
        self.assertEqual([{
            "namespaceSelector": {"matchLabels": {
                "kubernetes.io/metadata.name": "development-virtual-user-support"}},
            "podSelector": {"matchLabels": {"app": "horizon-support"}},
        }], rules[1]["from"])
        self.assertEqual([{"protocol":"TCP", "port":8080}], rules[1]["ports"])
        self.assertNotIn("namespaceSelector", rules[0]["from"][0])
        self.assertEqual({"from", "ports"}, set(rules[1]))
        self.assertEqual(2, len(policy["spec"]["egress"]))
        self.assertEqual([5000, 8774, 8778, 9696], [
            item["port"] for item in policy["spec"]["egress"][1]["ports"]])
