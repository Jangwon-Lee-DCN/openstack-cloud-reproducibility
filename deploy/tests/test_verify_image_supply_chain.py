#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest

PATH = pathlib.Path(__file__).with_name("verify_image_supply_chain.py")
if not PATH.exists():
    PATH = pathlib.Path(__file__).parents[1] / "scripts" / "verify_image_supply_chain.py"
SPEC = importlib.util.spec_from_file_location("supply", PATH)
MOD = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MOD)


class SupplyChainTest(unittest.TestCase):
    def files(self, critical=0):
        directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(directory.name)
        (root / "sbom.json").write_text(json.dumps({"bomFormat":"CycloneDX","components":[{"name":"ubuntu"}]}))
        (root / "scan.json").write_text(json.dumps({"summary":{"critical":critical,"high":2}}))
        return directory, root

    def test_accepts_no_critical_findings(self):
        tmp, root = self.files(); self.addCleanup(tmp.cleanup)
        MOD.verify(root / "sbom.json", root / "scan.json")

    def test_rejects_critical_findings(self):
        tmp, root = self.files(1); self.addCleanup(tmp.cleanup)
        with self.assertRaisesRegex(ValueError, "critical vulnerabilities"):
            MOD.verify(root / "sbom.json", root / "scan.json")


if __name__ == "__main__": unittest.main()
