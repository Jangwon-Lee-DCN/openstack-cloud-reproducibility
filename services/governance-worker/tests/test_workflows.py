import unittest
from decimal import Decimal

from governance_worker.workflows import (
    BudgetEvaluator, CertificatePhase, CertificateWorkflow, QueueEnvelope,
    RotationPhase, RotationWorkflow, WorkflowError,
)


class WorkflowTest(unittest.TestCase):
    def test_queue_contains_identifiers_only(self):
        envelope = QueueEnvelope("resource", "project", "operation", "request", 1)
        self.assertNotIn("secret", envelope.__dict__)

    def test_budget_threshold_is_once_per_period(self):
        evaluator = BudgetEvaluator()
        args = dict(budget_id="b", period="2026-08", amount=Decimal("100"),
                    spend=Decimal("91"), thresholds=[50, 80, 90, 100])
        self.assertEqual(evaluator.evaluate(**args), [50, 80, 90])
        self.assertEqual(evaluator.evaluate(**args), [])
        self.assertEqual(evaluator.evaluate(**{**args, "period": "2026-09"}), [50, 80, 90])

    def test_certificate_failure_retains_old_ref_and_requires_cleanup(self):
        workflow = CertificateWorkflow()
        workflow.challenge_created("designate://challenge")
        workflow.certificate_stored("barbican://candidate")
        workflow.apply_consumer("barbican://active")
        workflow.probe(False)
        self.assertEqual(workflow.rollback_ref(), "barbican://active")
        self.assertTrue(workflow.cleanup_required)
        workflow.challenge_cleaned()
        self.assertFalse(workflow.cleanup_required)

    def test_rotation_partial_failure_fully_rolls_back(self):
        workflow = RotationWorkflow(3, "barbican://v1", consumers={"lb": "barbican://v1", "app": "barbican://v1"})
        workflow.candidate_created("barbican://v2", expected_revision=3)
        workflow.consumer_updated("lb")
        workflow.begin_verification({"lb", "app"})
        self.assertEqual(workflow.phase, RotationPhase.ROLLING_BACK)
        workflow.rollback()
        self.assertEqual(workflow.consumers, {"lb": "barbican://v1", "app": "barbican://v1"})

    def test_rotation_revision_fencing(self):
        workflow = RotationWorkflow(2, "barbican://v1")
        with self.assertRaises(WorkflowError):
            workflow.candidate_created("barbican://v2", expected_revision=1)


if __name__ == "__main__":
    unittest.main()
