import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class IronicEvidenceTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "deploy/monitoring/manifests/ironic-evidence.yaml"
        self.documents = [item for item in yaml.safe_load_all(path.read_text()) if item]
        self.configmap = next(item for item in self.documents if item["kind"] == "ConfigMap")
        self.cronjob = next(item for item in self.documents if item["kind"] == "CronJob")
        self.script = self.configmap["data"]["run.sh"]

    def test_collector_exports_only_bounded_safe_ironic_evidence(self):
        for metric in (
            "openstack_ironic_node_info",
            "openstack_ironic_node_maintenance",
            "openstack_ironic_node_last_error",
            "openstack_ironic_node_validation_collected",
            "openstack_ironic_interface_supported",
            "openstack_ironic_interface_valid",
            "openstack_ironic_port_info",
            "openstack_ironic_evidence_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, self.script)
        self.assertIn("timeout 60 openstack baremetal node list", self.script)
        self.assertIn("timeout 60 openstack baremetal port list", self.script)
        self.assertIn("timeout 60 openstack baremetal node validate", self.script)
        self.assertIn("--request PUT --data-binary", self.script)
        self.assertNotIn("Driver Info", self.script)
        self.assertNotIn("ipmi_password", self.script)
        self.assertNotIn('"last_error":', self.script)

    def test_collector_is_packaged_but_not_production_enabled(self):
        self.assertEqual(
            "development-only",
            self.cronjob["metadata"]["annotations"]["dcn.ssu.ac.kr/lifecycle"],
        )
        container = self.cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        self.assertIn("@sha256:", container["image"])
        self.assertEqual(0, self.cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"])
        self.assertEqual(600, self.cronjob["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"])


if __name__ == "__main__":
    unittest.main()
