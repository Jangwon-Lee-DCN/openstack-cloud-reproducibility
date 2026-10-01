import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class PlacementEvidenceTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "deploy/monitoring/manifests/placement-evidence.yaml"
        self.documents = [item for item in yaml.safe_load_all(path.read_text()) if item]
        self.configmap = next(item for item in self.documents if item["kind"] == "ConfigMap")
        self.cronjob = next(item for item in self.documents if item["kind"] == "CronJob")
        self.script = self.configmap["data"]["run.sh"]

    def test_collector_exports_bounded_provider_inventory_and_traits(self):
        for metric in (
            "openstack_placement_provider_info",
            "openstack_placement_provider_inventory_collected",
            "openstack_placement_provider_trait_collection",
            "openstack_placement_provider_inventory_total",
            "openstack_placement_provider_inventory_used",
            "openstack_placement_provider_inventory_reserved",
            "openstack_placement_provider_inventory_allocation_ratio",
            "openstack_placement_provider_trait",
            "openstack_placement_allocation_candidate_collection",
            "openstack_placement_allocation_candidate_provider_count",
            "openstack_placement_evidence_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, self.script)
        self.assertIn("timeout 60 openstack resource provider list", self.script)
        self.assertIn("timeout 60 openstack resource provider inventory list", self.script)
        self.assertIn("timeout 60 openstack resource provider trait list", self.script)
        self.assertIn("--os-placement-api-version 1.29 allocation candidate list", self.script)
        self.assertIn("--limit 100", self.script)
        self.assertIn("general-small", self.script)
        self.assertIn("general-large", self.script)
        self.assertIn("gpu-custom-", self.script)
        self.assertIn("if collected:", self.script)
        self.assertNotIn("len(candidates) if collected else 0", self.script)
        self.assertIn("--request PUT --data-binary", self.script)
        self.assertNotIn("allocation show", self.script)
        self.assertNotIn("consumer", self.script)

    def test_collector_is_packaged_but_not_production_enabled(self):
        self.assertEqual("development-only", self.cronjob["metadata"]["annotations"]["dcn.ssu.ac.kr/lifecycle"])
        container = self.cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        self.assertIn("@sha256:", container["image"])
        self.assertEqual(0, self.cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"])
        self.assertEqual(900, self.cronjob["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"])


if __name__ == "__main__":
    unittest.main()
