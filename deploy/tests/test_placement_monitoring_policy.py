import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class PlacementMonitoringPolicyTests(unittest.TestCase):
    def test_reconciler_refuses_snapshot_policy_drift(self):
        reconciler = (ROOT / "deploy/scripts/reconcile-full-stack.sh").read_text()
        verifier = (ROOT / "deploy/scripts/verify-placement-monitoring-policy.sh").read_text()
        self.assertIn('verify-placement-monitoring-policy.sh', reconciler)
        for rule in (
            "placement:allocation_candidates:list",
            "placement:resource_providers:inventories:list",
            "placement:resource_providers:traits:list",
            "placement:traits:list",
        ):
            self.assertIn(rule, verifier)
        self.assertIn('"allocations:list"', verifier)
        self.assertIn('role:admin or role:monitoring', verifier)


if __name__ == "__main__":
    unittest.main()
