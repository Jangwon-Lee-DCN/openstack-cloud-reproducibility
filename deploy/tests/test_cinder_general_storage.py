import base64
import pathlib
import subprocess
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class CinderGeneralStorageTests(unittest.TestCase):
    def test_site_values_publish_bounded_general_purpose_cache(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/cinder.yaml").read_text())
        default = values["conf"]["cinder"]["DEFAULT"]
        backend = values["conf"]["backends"]["rbd1"]
        self.assertEqual("general-purpose", default["default_volume_type"])
        self.assertTrue(backend["image_volume_cache_enabled"])
        self.assertEqual(500, backend["image_volume_cache_max_size_gb"])
        self.assertEqual(20, backend["image_volume_cache_max_count"])
        self.assertEqual(
            "POWERSTORE",
            values["bootstrap"]["volume_types"]["general-purpose"]["volume_backend_name"],
        )
        self.assertTrue(values["conf"]["enable_iscsi"])

    def test_helm_render_contains_service_contract(self):
        rendered = subprocess.check_output(
            [
                "helm", "template", "cinder",
                str(ROOT / "helm/packages/patched/cinder-2026.1.0.tgz"),
                "-f", str(ROOT / "deploy/values/site/cinder.yaml"),
            ], text=True
        )
        objects = [item for item in yaml.safe_load_all(rendered) if item]
        secret = next(
            item for item in objects
            if item.get("kind") == "Secret" and item.get("metadata", {}).get("name") == "cinder-etc"
        )
        config = base64.b64decode(secret["data"]["cinder.conf"]).decode()
        backends = base64.b64decode(secret["data"]["backends.conf"]).decode()
        self.assertIn("default_volume_type = general-purpose", config)
        self.assertIn("image_volume_cache_enabled = true", backends)
        self.assertIn("image_volume_cache_max_size_gb = 500", backends)
        volume = next(
            item for item in objects
            if item.get("kind") == "Deployment"
            and item.get("metadata", {}).get("name") == "cinder-volume"
        )
        pod = volume["spec"]["template"]["spec"]
        host_paths = {
            entry["name"]: entry["hostPath"]["path"]
            for entry in pod["volumes"] if "hostPath" in entry
        }
        self.assertEqual("/dev", host_paths["host-dev"])
        self.assertEqual("/sys", host_paths["sys"])
        container = next(item for item in pod["containers"] if item["name"] == "cinder-volume")
        mounts = {item["mountPath"]: item for item in container["volumeMounts"]}
        self.assertEqual("host-dev", mounts["/dev"]["name"])
        self.assertEqual("Bidirectional", mounts["/etc/multipath"]["mountPropagation"])
        compat_mount = mounts["/var/lib/openstack/lib/python3.12/site-packages/cinder_powerstore_compat.py"]
        self.assertEqual("powerstore-legacy-host-api", compat_mount["name"])
        self.assertIn(
            "/var/lib/openstack/lib/python3.12/site-packages/cinder-powerstore-compat.pth",
            mounts,
        )

    def test_synthetic_cleanup_recovers_error_volume_without_create_id(self):
        manifest = yaml.safe_load_all(
            (ROOT / "deploy/monitoring/manifests/synthetic-test.yaml").read_text()
        )
        configmap = next(item for item in manifest if item["kind"] == "ConfigMap")
        script = configmap["data"]["run.sh"]
        self.assertIn('volume list --name "${name}"', script)
        self.assertIn('volume delete --force "${stale_volume_id}"', script)
        self.assertIn("dcn_synthetic_test=true", script)

    def test_synthetic_proves_object_auth_write_read_and_cleanup(self):
        manifest = yaml.safe_load_all(
            (ROOT / "deploy/monitoring/manifests/synthetic-test.yaml").read_text()
        )
        configmap = next(item for item in manifest if item["kind"] == "ConfigMap")
        script = configmap["data"]["run.sh"]
        for metric in (
            "openstack_synthetic_object_auth_success",
            "openstack_synthetic_object_write_success",
            "openstack_synthetic_object_read_success",
            "openstack_synthetic_object_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, script)
        self.assertIn("openstack --os-interface internal container list", script)
        self.assertIn("openstack --os-interface internal object create", script)
        self.assertIn('--name "${object_name}"', script)
        self.assertIn("openstack --os-interface internal object save --file", script)
        self.assertIn('cmp -s "${object_payload}" "${object_received}"', script)
        self.assertIn("openstack --os-interface internal object delete", script)
        self.assertIn("openstack --os-interface internal container delete", script)

    def test_synthetic_collects_oidc_discovery_and_google_broker_handoff(self):
        manifest = list(
            yaml.safe_load_all(
                (ROOT / "deploy/monitoring/manifests/synthetic-test.yaml").read_text()
            )
        )
        configmap = next(item for item in manifest if item["kind"] == "ConfigMap")
        cronjob = next(item for item in manifest if item["kind"] == "CronJob")
        script = configmap["data"]["run.sh"]
        for metric in (
            "openstack_identity_oidc_discovery_success",
            "openstack_identity_google_broker_redirect_success",
            "openstack_identity_oidc_last_run_timestamp_seconds",
        ):
            self.assertIn(metric, script)
        self.assertIn("/.well-known/openid-configuration", script)
        self.assertIn('"kc_idp_hint": "google"', script)
        self.assertIn('host == "accounts.google.com"', script)
        self.assertIn('error.headers.get_all("Set-Cookie")', script)
        env = {
            item["name"]: item["value"]
            for item in cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["env"]
        }
        self.assertEqual("dcn-operations-portal", env["OIDC_CLIENT_ID"])
        self.assertEqual(
            "https://platform.dcn.ssu.ac.kr/auth/callback", env["OIDC_REDIRECT_URI"]
        )
        self.assertEqual(
            "https://cloud.dcn.ssu.ac.kr/horizon/auth/idp/realms/dcn",
            env["OIDC_EXPECTED_ISSUER"],
        )

    def test_storage_link_observability_uses_live_metric_contract(self):
        alerts = (ROOT / "deploy/monitoring/manifests/alerts.yaml").read_text()
        dashboards = (ROOT / "deploy/monitoring/manifests/openstack-service-dashboards.yaml").read_text()
        for metric in (
            "node_network_speed_bytes", "node_network_receive_bytes_total",
            "node_network_receive_errs_total", "node_network_receive_drop_total",
        ):
            self.assertIn(metric, alerts)
            self.assertIn(metric, dashboards)
        self.assertIn("StorageFabricLinkSaturation", alerts)
        self.assertIn("StorageFabricPacketErrors", alerts)

    def test_image_cache_acceptance_is_bounded_and_self_cleaning(self):
        guest = (ROOT / "deploy/acceptance/cinder-image-volume-cache.sh").read_text()
        runner = (ROOT / "deploy/scripts/verify-cinder-image-volume-cache.sh").read_text()
        self.assertIn("CINDER_ACCEPTANCE_TIMEOUT_SECONDS", guest)
        self.assertIn("trap cleanup EXIT", guest)
        self.assertIn("--image", guest)
        self.assertIn("warm_to_cold_ratio", guest)
        self.assertIn("activeDeadlineSeconds: 2700", runner)
        self.assertIn("keystone-keystone-admin", runner)
        self.assertIn("@sha256:", runner)
        self.assertIn("status.failed", runner)

    def test_powerstore_legacy_host_api_compatibility_is_scoped(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/cinder.yaml").read_text())
        configmap = next(
            item for item in values["extraObjects"]
            if item["metadata"]["name"] == "cinder-powerstore-legacy-host-api"
        )
        self.assertEqual("import cinder_powerstore_compat\n", configmap["data"]["cinder-powerstore-compat.pth"])
        patch = configmap["data"]["cinder_powerstore_compat.py"]
        compile(patch, "cinder_powerstore_compat.py", "exec")
        self.assertIn("unknown_host_connectivity", patch)
        self.assertIn("builtins.__import__ = _compat_import", patch)
        self.assertIn("adapter.CommonAdapter._modify_host_connectivity", patch)
        self.assertIn('"select": "id,name,host_initiators"', patch)
        self.assertIn("_dcn_legacy_host_api", patch)
        self.assertNotIn("verify=False", patch)


if __name__ == "__main__":
    unittest.main()
