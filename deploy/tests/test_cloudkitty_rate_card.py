import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


class CloudKittyRateCardContract(unittest.TestCase):
    def test_catalog_matches_processor_and_immutable_hashmap_bootstrap(self):
        catalog = yaml.safe_load((ROOT / "deploy/config/cloudkitty-rate-card.v1.yaml").read_text())
        values = yaml.safe_load((ROOT / "deploy/values/site/cloudkitty.yaml").read_text())
        meters = {item["name"]: str(item["unitPrice"]) for item in catalog["spec"]["meters"]}
        processor = values["conf"]["processor_metrics"]
        bootstrap = values["bootstrap"]["script"]
        self.assertEqual(catalog["metadata"]["name"], "dcn-showback-v1")
        self.assertFalse(catalog["spec"]["billing"])
        for meter, price in meters.items():
            self.assertTrue(f"{meter}:" in processor or f"alt_name: {meter}" in processor, meter)
            self.assertIn(f"ensure_rate {meter} {price}", bootstrap)
        self.assertIn("--start 2026-08-01T00:00:00Z", bootstrap)

    def test_every_rendered_workload_image_is_immutable(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/cloudkitty.yaml").read_text())
        for name, image in values["images"]["tags"].items():
            if name == "image_repo_sync":
                continue
            self.assertIn("@sha256:", image, name)

    def test_control_plane_toleration_is_enabled(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/cloudkitty.yaml").read_text())
        self.assertTrue(values["pod"]["tolerations"]["cloudkitty"]["enabled"])

    def test_reconciler_uses_digest_pinned_patched_chart(self):
        script = (ROOT / "deploy/scripts/reconcile-cloudkitty.sh").read_text()
        self.assertIn("helm/packages/patched/cloudkitty-2026.1.0.tgz", script)
        self.assertIn(
            "cfb0df843ccb9d23bb0d8e8966bddd90532c41c1260b2e96c1a962b5ae05702e",
            script,
        )

    def test_rate_bootstrap_runs_after_keystone_hooks(self):
        template = (
            ROOT / "helm/openstack-helm/cloudkitty/templates/job-bootstrap.yaml"
        ).read_text()
        self.assertIn("helm.sh/hook: post-install,post-upgrade", template)
        self.assertIn('helm.sh/hook-weight: "0"', template)
        self.assertIn('set $bootstrapJob "jobAnnotations"', template)

    def test_dependency_jobs_are_regular_release_resources(self):
        names = (
            "job-db-init.yaml",
            "job-db-sync.yaml",
            "job-rabbitmq-init.yaml",
            "job-storage-init.yaml",
            "job-ks-service.yaml",
            "job-ks-endpoints.yaml",
            "job-ks-user.yaml",
        )
        for name in names:
            template = (ROOT / "helm/openstack-helm/cloudkitty/templates" / name).read_text()
            self.assertNotIn("pre-install,pre-upgrade", template, name)
            self.assertNotIn("post-install,post-upgrade", template, name)

    def test_reconciler_recreates_exact_dependency_jobs_on_upgrade(self):
        script = (ROOT / "deploy/scripts/reconcile-cloudkitty.sh").read_text()
        for name in (
            "cloudkitty-db-init",
            "cloudkitty-db-sync",
            "cloudkitty-rabbit-init",
            "cloudkitty-storage-init",
            "cloudkitty-ks-service",
            "cloudkitty-ks-endpoints",
            "cloudkitty-ks-user",
        ):
            self.assertIn(name, script)

    def test_storage_retry_is_exact_and_fail_closed(self):
        script = (ROOT / "deploy/scripts/reconcile-cloudkitty.sh").read_text()
        self.assertIn("retry-storage-init", script)
        self.assertIn('len(matches) != 1', script)
        self.assertIn("job/cloudkitty-storage-init --timeout=10m", script)
        self.assertIn("kubectl logs", script)

    def test_mariadb_uses_the_available_v1_sql_storage_driver(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/cloudkitty.yaml").read_text())
        storage = values["conf"]["cloudkitty"]["storage"]
        self.assertEqual(storage, {"backend": "sqlalchemy", "version": 1})


if __name__ == "__main__":
    unittest.main()
