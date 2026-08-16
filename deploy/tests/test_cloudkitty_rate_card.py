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
            "d2d26ef7dc3c6e5579beb08ce5a6fdf28f091788ebfa2f45d30101cfb9746a0f",
            script,
        )

    def test_rate_bootstrap_runs_after_keystone_hooks(self):
        template = (
            ROOT / "helm/openstack-helm/cloudkitty/templates/job-bootstrap.yaml"
        ).read_text()
        self.assertIn("helm.sh/hook: post-install,post-upgrade", template)
        self.assertIn('helm.sh/hook-weight: "0"', template)
        self.assertIn('set $bootstrapJob "jobAnnotations"', template)

    def test_dependency_jobs_run_before_atomic_workload_wait(self):
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
            self.assertIn("pre-install,pre-upgrade", template, name)
            self.assertNotIn("post-install,post-upgrade", template, name)


if __name__ == "__main__":
    unittest.main()
