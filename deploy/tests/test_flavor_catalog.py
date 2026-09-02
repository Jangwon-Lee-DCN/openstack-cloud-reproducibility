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
        self.assertEqual("FLAVOR_CATALOG_IMAGE", deployment["spec"]["template"]["spec"]["containers"][0]["image"])
        self.assertEqual("ClusterIP", service["spec"].get("type", "ClusterIP"))
        self.assertEqual(["Ingress", "Egress"], policy["spec"]["policyTypes"])
        self.assertNotIn("HTTPRoute", [x["kind"] for x in docs])

    def test_only_horizon_can_reach_the_api(self):
        policy = list(yaml.safe_load_all((ROOT / "manifests/flavor-catalog.yaml").read_text()))[-1]
        source = policy["spec"]["ingress"][0]["from"][0]
        self.assertEqual("horizon", source["podSelector"]["matchLabels"]["application"])
