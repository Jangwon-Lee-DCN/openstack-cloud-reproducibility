import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[1]


class GPUImageContractTest(unittest.TestCase):
    def test_contract_is_private_pinned_and_unbooted(self):
        value = yaml.safe_load((ROOT / "config/gpu-image-contract.yaml").read_text())
        self.assertEqual("dcn.ssu.ac.kr/gpu-image/v1", value["schema"])
        self.assertEqual("private", value["visibility"])
        self.assertTrue(value["protected"])
        self.assertEqual("unbooted", value["properties"]["dcn_gpu_validation"])
        self.assertFalse(value["publication_gate"]["allow_project_access_before_guest_validation"])
        self.assertTrue(value["publication_gate"]["require_guest_vm"])
        for version in value["packages"].values():
            self.assertNotIn("latest", str(version).lower())

    def test_builder_requires_base_digest_and_exact_packages(self):
        script = (ROOT / "scripts/build-gpu-glance-image.sh").read_text()
        self.assertIn("GPU_BASE_SHA256", script)
        self.assertIn("sha256sum --check", script)
        self.assertIn('f"{name}={version}"', script)
        self.assertIn("qemu-img check", script)


if __name__ == "__main__":
    unittest.main()
