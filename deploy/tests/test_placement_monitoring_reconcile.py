import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class PlacementMonitoringReconcileTests(unittest.TestCase):
    def test_check_mode_validates_exact_chart_without_mutation(self):
        script = (ROOT / "deploy/scripts/reconcile-placement-monitoring-policy.sh").read_text()
        self.assertIn("verify-placement-monitoring-policy.sh", script)
        self.assertIn("render-region-values.py", script)
        self.assertIn("placement-2026.1.0.tgz", script)
        self.assertIn("kubectl apply --dry-run=server -f -", script)
        self.assertIn("ONLY_RELEASE=placement", script)
        self.assertIn("VERIFY_AFTER_RECONCILE=0", script)
        self.assertLess(script.index("if [[ \"$mode\" == --check ]]"), script.index("ONLY_RELEASE=placement"))


if __name__ == "__main__":
    unittest.main()
