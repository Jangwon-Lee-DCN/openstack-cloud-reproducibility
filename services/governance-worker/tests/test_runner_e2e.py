import os
import subprocess
import sys
import tempfile
import unittest

from governance_api.security import RequestContext
from governance_api.service import GovernanceService
from governance_api.store import Store
from governance_worker.runner import RealScheduler


class RecordingBus:
    def __init__(self): self.events = []
    def publish(self, event): self.events.append(event)


class RunnerE2ETest(unittest.TestCase):
    def test_restart_resumes_persisted_outbox(self):
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/governance.db"
            service = GovernanceService(Store(path))
            service.create_budget(RequestContext("d", "p", "u"), {"amount": "10"}, key="budget-key", request_id="req")
            bus = RecordingBus()
            first_process = RealScheduler(Store(path), bus, owner="worker-before-restart")
            self.assertEqual(first_process.run_once()["delivered"], 1)
            second_process = RealScheduler(Store(path), bus, owner="worker-after-restart")
            self.assertEqual(second_process.run_once()["claimed"], 0)

    def test_production_mode_fails_closed(self):
        env = dict(os.environ, GOVERNANCE_MODE="production", GOVERNANCE_RUN_ONCE="1")
        result = subprocess.run([sys.executable, "-m", "governance_worker.runner"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"development boundary is required", result.stderr)


if __name__ == "__main__":
    unittest.main()
