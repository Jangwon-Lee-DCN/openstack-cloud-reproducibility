import subprocess
import tempfile
import unittest
import importlib.util
from pathlib import Path

import yaml

module_path = Path(__file__).parents[1] / "scripts" / "verify-cloudkitty-source-lock.py"
spec = importlib.util.spec_from_file_location("verify_cloudkitty_source_lock", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
verify = module.verify


class SourceLockTests(unittest.TestCase):
    def repository(self, root: Path):
        subprocess.run(["git", "init", "-b", "main", str(root)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
        (root / "tracked").write_text("x")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "initial"], check=True,
                       stdout=subprocess.DEVNULL)

    def test_exact_dual_lock_passes_and_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            portable, site = Path(directory, "portable"), Path(directory, "site")
            portable.mkdir(); site.mkdir(); self.repository(portable); self.repository(site)
            revision = subprocess.check_output(["git", "-C", str(portable), "rev-parse", "HEAD"], text=True).strip()
            automation = site / "automation"; automation.mkdir()
            document = {"repositories": {"reproducibility": {"revision": revision}}}
            for name in ("development-repositories.lock.yaml", "repositories.lock.yaml"):
                (automation / name).write_text(yaml.safe_dump(document))
            subprocess.run(["git", "-C", str(site), "add", "."], check=True)
            subprocess.run(["git", "-C", str(site), "commit", "-m", "locks"], check=True,
                           stdout=subprocess.DEVNULL)
            self.assertEqual(verify(portable, site), revision)
            document["repositories"]["reproducibility"]["revision"] = "0" * 40
            (automation / "repositories.lock.yaml").write_text(yaml.safe_dump(document))
            subprocess.run(["git", "-C", str(site), "add", "."], check=True)
            subprocess.run(["git", "-C", str(site), "commit", "-m", "mismatch"], check=True,
                           stdout=subprocess.DEVNULL)
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                verify(portable, site)


if __name__ == "__main__":
    unittest.main()
