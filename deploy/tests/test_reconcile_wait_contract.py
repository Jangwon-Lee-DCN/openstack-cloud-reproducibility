from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReconcileWaitContractTests(unittest.TestCase):
    def test_reconciler_allows_phase_owned_readiness_wait(self):
        script = (ROOT / "deploy/scripts/reconcile-full-stack.sh").read_text()

        self.assertIn("WAIT_AFTER_RECONCILE=${WAIT_AFTER_RECONCILE:-1}", script)
        self.assertIn('if [[ "$WAIT_AFTER_RECONCILE" == "1" ]]', script)
        self.assertIn('WAIT_AFTER_RECONCILE must be 0 or 1', script)


if __name__ == "__main__":
    unittest.main()
