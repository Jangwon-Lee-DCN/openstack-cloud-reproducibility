import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class GatewayApiEvidenceTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / "deploy/monitoring/manifests/gateway-api-evidence.yaml"
        self.documents = [item for item in yaml.safe_load_all(path.read_text()) if item]
        self.configmap = next(item for item in self.documents if item["kind"] == "ConfigMap")
        self.cronjob = next(item for item in self.documents if item["kind"] == "CronJob")
        self.role = next(item for item in self.documents if item["kind"] == "ClusterRole")
        self.script = self.configmap["data"]["run.py"]

    def test_collector_exports_bounded_aggregate_route_evidence(self):
        for metric in (
            "openstack_gateway_api_collection",
            "openstack_gateway_api_routes_total",
            "openstack_gateway_api_accepted_routes",
            "openstack_gateway_api_rejected_or_pending_routes",
            "openstack_gateway_api_gateways_total",
            "openstack_gateway_api_programmed_gateways",
            "openstack_gateway_api_evidence_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, self.script)
        self.assertIn('condition.get("type") == "Accepted"', self.script)
        self.assertNotIn('route["metadata"]["name"]', self.script)
        self.assertNotIn('route["metadata"]["namespace"]', self.script)

    def test_collector_has_read_only_gateway_api_rbac(self):
        self.assertEqual(["get", "list"], self.role["rules"][0]["verbs"])
        self.assertEqual(["gateway.networking.k8s.io"], self.role["rules"][0]["apiGroups"])
        self.assertNotIn("watch", self.role["rules"][0]["verbs"])

    def test_collector_is_packaged_but_not_production_enabled(self):
        self.assertEqual(
            "development-only",
            self.cronjob["metadata"]["annotations"]["dcn.ssu.ac.kr/lifecycle"],
        )
        container = self.cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
        self.assertIn("@sha256:", container["image"])
        self.assertEqual(0, self.cronjob["spec"]["jobTemplate"]["spec"]["backoffLimit"])
        self.assertEqual(120, self.cronjob["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"])


if __name__ == "__main__":
    unittest.main()
