import copy
import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/scripts/check-vpc-facade-lock-consistency.py"
spec = importlib.util.spec_from_file_location("facade_consistency", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FacadeConsistencyTest(unittest.TestCase):
    def setUp(self):
        self.image = "registry.invalid/facade@sha256:" + "a" * 64
        self.composite = {"spec": {"facadeImage": self.image, "sourceRevision": "b" * 40}}
        self.scoped = {"schema": 1, "component": "vpc-facade-credential-trust",
                       "candidate": {"image": self.image, "source_revision": "b" * 40}}

    def test_matching_inputs(self):
        module.check(self.composite, self.scoped)

    def test_predecessor_cannot_override_candidate(self):
        self.composite["spec"]["facadeImage"] = self.image.replace("a" * 64, "c" * 64)
        with self.assertRaises(ValueError):
            module.check(self.composite, self.scoped)

    def test_source_mismatch_rejected(self):
        self.composite["spec"]["sourceRevision"] = "c" * 40
        with self.assertRaises(ValueError):
            module.check(self.composite, self.scoped)

    def test_invalid_inputs(self):
        for field, value in (("source_revision", "main"), ("image", "facade:latest")):
            scoped = copy.deepcopy(self.scoped)
            scoped["candidate"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.check(self.composite, scoped)
        self.scoped["component"] = "wrong"
        with self.assertRaises(ValueError):
            module.check(self.composite, self.scoped)

    def test_missing_files_fail_closed(self):
        result = subprocess.run(["python3", str(SCRIPT), "/nonexistent/composite", "/nonexistent/scoped"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    def test_installer_checks_before_any_kubernetes_command(self):
        source = (ROOT / "deploy/scripts/install-vpc-policy-plane.sh").read_text()
        self.assertLess(source.index("check-vpc-facade-lock-consistency.py"), source.index("kubectl "))


if __name__ == "__main__":
    unittest.main()
