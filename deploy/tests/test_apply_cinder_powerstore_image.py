import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/scripts/apply-cinder-powerstore-image.py"
spec = importlib.util.spec_from_file_location("apply_cinder_image", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ApplyCinderImageTest(unittest.TestCase):
    def test_updates_only_volume_image_and_requires_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = Path(temporary) / "cinder.yaml"
            values.write_text("images:\n  tags:\n    cinder_api: upstream\n    cinder_volume: upstream\n")
            ref = "registry.dcn.ssu.ac.kr/openstack/cinder:source-test@sha256:" + "a" * 64
            with mock.patch.object(module, "VALUES", values):
                self.assertTrue(module.apply(ref, write=True))
                self.assertFalse(module.apply(ref, write=True))
                with self.assertRaises(ValueError):
                    module.apply("registry.dcn.ssu.ac.kr/openstack/cinder:latest", write=False)
            rendered = values.read_text()
            self.assertIn(f"cinder_volume: {ref}", rendered)
            self.assertIn("cinder_api: upstream", rendered)


if __name__ == "__main__":
    unittest.main()

