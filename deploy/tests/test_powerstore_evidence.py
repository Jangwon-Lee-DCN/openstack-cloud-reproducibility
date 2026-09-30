import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class PowerStoreEvidenceManifestTests(unittest.TestCase):
    def setUp(self):
        self.documents = list(
            yaml.safe_load_all(
                (ROOT / "deploy/monitoring/manifests/powerstore-evidence.yaml").read_text()
            )
        )

    def test_collector_uses_existing_secret_and_read_only_metrics_query(self):
        cronjob = next(item for item in self.documents if item["kind"] == "CronJob")
        pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        secret = next(item for item in pod["volumes"] if item["name"] == "powerstore-config")
        self.assertEqual(secret["secret"]["secretName"], "powerstore-config")
        container = pod["containers"][0]
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])

        configmap = next(item for item in self.documents if item["kind"] == "ConfigMap")
        script = configmap["data"]["run.py"]
        self.assertIn('"entity": "space_metrics_by_cluster"', script)
        self.assertIn('f"{endpoint}/metrics/generate"', script)
        self.assertIn('array_id="{array_id}"', script)
        self.assertIn('array.get("globalID")', script)
        self.assertNotIn("volume/", script)
        self.assertNotIn("DELETE", script)
        for metric in (
            "openstack_powerstore_array_pressure",
            "openstack_powerstore_physical_total_bytes",
            "openstack_powerstore_physical_used_bytes",
            "openstack_powerstore_physical_free_bytes",
            "openstack_powerstore_data_reduction_ratio",
            "openstack_powerstore_evidence_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, script)

    def test_network_policy_is_bounded_to_dns_array_and_pushgateway(self):
        policy = next(item for item in self.documents if item["kind"] == "NetworkPolicy")
        self.assertEqual(policy["spec"]["ingress"], [])
        rendered = yaml.safe_dump(policy)
        self.assertIn("192.168.40.124/32", rendered)
        self.assertIn("prometheus-pushgateway", rendered)
        self.assertNotIn("0.0.0.0/0", rendered)


if __name__ == "__main__":
    unittest.main()
