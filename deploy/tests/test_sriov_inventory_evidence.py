import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class SriovInventoryEvidenceTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "deploy/monitoring/manifests/sriov-inventory-evidence.yaml"
        self.documents = [item for item in yaml.safe_load_all(path.read_text()) if item]
        self.configmap = next(item for item in self.documents if item["kind"] == "ConfigMap")
        self.daemonset = next(item for item in self.documents if item["kind"] == "DaemonSet")
        self.policy = next(item for item in self.documents if item["kind"] == "NetworkPolicy")

    def test_reads_only_bounded_host_sysfs_inventory(self):
        script = self.configmap["data"]["run.sh"]
        self.assertIn("/host-sys/class/net/*/device/sriov_totalvfs", script)
        self.assertIn("sriov_numvfs", script)
        self.assertIn("openstack_sriov_pf_total_vfs", script)
        self.assertIn("openstack_sriov_pf_configured_vfs", script)
        self.assertNotIn("ip link", script)
        self.assertNotIn("echo ${", script)

    def test_daemonset_is_unprivileged_read_only_and_sriov_scoped(self):
        template = self.daemonset["spec"]["template"]["spec"]
        self.assertEqual({"sriov": "enabled"}, template["nodeSelector"])
        container = template["containers"][0]
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(["ALL"], container["securityContext"]["capabilities"]["drop"])
        host_sys = next(volume for volume in template["volumes"] if volume["name"] == "host-sys")
        self.assertEqual("/sys", host_sys["hostPath"]["path"])
        mount = next(item for item in container["volumeMounts"] if item["name"] == "host-sys")
        self.assertTrue(mount["readOnly"])
        self.assertIn("@sha256:", container["image"])

    def test_policy_allows_only_dns_and_pushgateway(self):
        self.assertEqual([], self.policy["spec"]["ingress"])
        ports = {
            (port["protocol"], port["port"])
            for rule in self.policy["spec"]["egress"]
            for port in rule["ports"]
        }
        self.assertEqual({("UDP", 53), ("TCP", 53), ("TCP", 9091)}, ports)


if __name__ == "__main__":
    unittest.main()
