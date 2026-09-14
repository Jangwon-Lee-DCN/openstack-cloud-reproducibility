import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "images/cinder-powerstore-legacy-api/apply_compatibility.py"
spec = importlib.util.spec_from_file_location("powerstore_compat", PATCHER)
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


class PowerStoreLegacyApiImageTest(unittest.TestCase):
    def test_patch_removes_unsupported_field_and_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "client.py").write_text(
                '"select": "id,name,host_initiators,host_connectivity",\n'
                '                "initiators": ports,\n'
                '                "host_connectivity": connectivity,\n'
            )
            (root / "adapter.py").write_text(
                '        if host["host_connectivity"] != self.host_connectivity:\n'
            )
            compat.patch_driver(root)
            client = (root / "client.py").read_text()
            adapter = (root / "adapter.py").read_text()
            self.assertIn('"select": "id,name,host_initiators",', client)
            self.assertNotIn('"host_connectivity": connectivity', client)
            self.assertIn('"host_connectivity" in host', adapter)
            with self.assertRaises(RuntimeError):
                compat.patch_driver(root)

    def test_image_keeps_the_pinned_2026_1_base(self):
        dockerfile = (ROOT / "images/cinder-powerstore-legacy-api/Dockerfile").read_text()
        self.assertIn(
            "FROM quay.io/airshipit/cinder:2026.1-ubuntu_noble@sha256:",
            dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
