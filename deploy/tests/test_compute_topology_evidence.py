import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class ComputeTopologyEvidenceTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "deploy/monitoring/manifests/compute-topology-evidence.yaml"
        self.documents = [item for item in yaml.safe_load_all(path.read_text()) if item]
        self.configmap = next(item for item in self.documents if item["kind"] == "ConfigMap")
        self.daemonset = next(item for item in self.documents if item["kind"] == "DaemonSet")
        self.policy = next(item for item in self.documents if item["kind"] == "NetworkPolicy")
        self.script = self.configmap["data"]["run.sh"]

    def test_collector_exports_bounded_numa_and_pci_topology(self):
        for metric in (
            "openstack_compute_topology_collected",
            "openstack_compute_numa_node_info",
            "openstack_compute_numa_cpu_count",
            "openstack_compute_numa_memory_bytes",
            "openstack_compute_pci_device_info",
            "openstack_compute_topology_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, self.script)
        self.assertIn("/host-sys/devices/system/node/node[0-9]*", self.script)
        self.assertIn("/host-sys/bus/pci/devices/*", self.script)
        self.assertIn("0x02*:*|0x03*:*|*:vfio-pci", self.script)
        self.assertNotIn("lspci", self.script)
        self.assertIn("urllib.request", self.script)
        self.assertNotIn("curl ", self.script)

    def test_collector_is_read_only_development_evidence_on_compute_nodes(self):
        self.assertEqual(
            "development-only",
            self.daemonset["metadata"]["annotations"]["dcn.ssu.ac.kr/lifecycle"],
        )
        pod = self.daemonset["spec"]["template"]["spec"]
        self.assertEqual({"openstack-compute-node": "enabled"}, pod["nodeSelector"])
        host_sys = next(volume for volume in pod["volumes"] if volume["name"] == "host-sys")
        self.assertEqual({"path": "/sys", "type": "Directory"}, host_sys["hostPath"])
        container = pod["containers"][0]
        self.assertTrue(container["image"].startswith("registry.dcn.ssu.ac.kr/"))
        self.assertIn("@sha256:", container["image"])
        sys_mount = next(
            mount for mount in container["volumeMounts"] if mount["name"] == "host-sys"
        )
        self.assertTrue(sys_mount["readOnly"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(["ALL"], container["securityContext"]["capabilities"]["drop"])
        self.assertEqual([], self.policy["spec"]["ingress"])


if __name__ == "__main__":
    unittest.main()
