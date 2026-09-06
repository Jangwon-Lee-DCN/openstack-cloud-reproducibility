import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "bin" / "reconcile-coredns-authoritative-zone.py"
SPEC = importlib.util.spec_from_file_location("coredns_forward", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CoreDNSAuthoritativeZoneTests(unittest.TestCase):
    def test_preserves_default_server_and_inserts_private_zone(self):
        source = ".:53 {\n    forward . /etc/resolv.conf\n}\n"
        result = MODULE.render_corefile(source, "dcn.ssu.ac.kr", ["10.64.20.12", "10.65.20.12"])
        self.assertIn("dcn.ssu.ac.kr:53", result)
        self.assertIn("forward . 10.64.20.12 10.65.20.12", result)
        self.assertIn("forward . /etc/resolv.conf", result)

    def test_reconciliation_is_idempotent(self):
        source = ".:53 {\n    forward . /etc/resolv.conf\n}\n"
        once = MODULE.render_corefile(source, "dcn.ssu.ac.kr", ["10.64.20.12", "10.65.20.12"])
        twice = MODULE.render_corefile(once, "dcn.ssu.ac.kr", ["10.64.20.12", "10.65.20.12"])
        self.assertEqual(once, twice)
        self.assertEqual(1, twice.count(MODULE.START))


if __name__ == "__main__":
    unittest.main()
