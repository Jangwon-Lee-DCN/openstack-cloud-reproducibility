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
            "37383178b564d1fbccf1cbdc42f40f0f6a774d7156ad73add8ba898d7f2163c4",
            script,
        )


if __name__ == "__main__":
    unittest.main()
