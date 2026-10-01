import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class NetworkEvidenceTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "deploy/monitoring/manifests/network-evidence.yaml"
        self.documents = [item for item in yaml.safe_load_all(path.read_text()) if item]
        self.configmap = next(item for item in self.documents if item["kind"] == "ConfigMap")
        self.cronjob = next(item for item in self.documents if item["kind"] == "CronJob")
        self.script = self.configmap["data"]["run.sh"]

    def test_collector_exports_only_bounded_binding_aggregates(self):
        for metric in (
            "openstack_neutron_port_binding_info",
            "openstack_neutron_sriov_attachment_count",
            "openstack_neutron_port_binding_failures",
            "openstack_network_evidence_collected",
            "openstack_network_evidence_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, self.script)
        self.assertIn("openstack.connect(verify=False).network.ports()", self.script)
        self.assertIn('host=\\"all\\",vnic_type=\\"direct\\",status=\\"all\\"', self.script)
        self.assertNotIn("port.id", self.script)
        self.assertNotIn("fixed_ips", self.script)
        self.assertNotIn("mac_address", self.script)
        self.assertNotIn("binding_profile", self.script)

    def test_collector_is_packaged_but_not_production_enabled(self):
        self.assertEqual("development-only", self.cronjob["metadata"]["annotations"]["dcn.ssu.ac.kr/lifecycle"])
        container = self.cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        self.assertIn("@sha256:", container["image"])
        self.assertEqual(0, self.cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"])
        self.assertEqual(180, self.cronjob["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"])


if __name__ == "__main__":
    unittest.main()
