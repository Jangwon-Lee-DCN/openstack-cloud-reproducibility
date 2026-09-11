import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/scripts/kubernetes-image-build-name.py"
spec = importlib.util.spec_from_file_location("build_name", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class KubernetesImageBuildNameTest(unittest.TestCase):
    def test_long_names_are_valid_bounded_and_collision_resistant(self):
        first = module.build_name("cinder-powerstore-legacy-api", "c7fcae665b5821418571042")
        second = module.build_name("cinder-powerstore-legacy-agent", "c7fcae665b5821418571042")
        self.assertLessEqual(len(first), 63)
        self.assertRegex(first, r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
