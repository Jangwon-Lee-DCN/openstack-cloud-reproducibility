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


if __name__ == "__main__":
    unittest.main()
