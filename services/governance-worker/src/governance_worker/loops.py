from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .tags import FakeNativeTagAdapter, TagReconciler
from .workflows import BudgetEvaluator, CertificateWorkflow, RotationWorkflow


@dataclass
class DeterministicProviders:
    spend: dict[str, Decimal] = field(default_factory=dict)
    budget_events: list[tuple[str, int]] = field(default_factory=list)
    certificate_refs: dict[str, str] = field(default_factory=dict)
    rotation_refs: dict[str, str] = field(default_factory=dict)
    tag_adapter: FakeNativeTagAdapter = field(default_factory=lambda: FakeNativeTagAdapter("fake"))


class FakeReconciliationLoops:
    def __init__(self, providers: DeterministicProviders):
        self.providers = providers
        self.budgets = BudgetEvaluator()

    def budget(self, budget_id: str, period: str, amount: Decimal, thresholds: list[int]):
        events = self.budgets.evaluate(
            budget_id=budget_id, period=period, amount=amount,
            spend=self.providers.spend.get(budget_id, Decimal("0")), thresholds=thresholds)
        self.providers.budget_events.extend((budget_id, threshold) for threshold in events)
        return events

    def certificate(self, policy_id: str, previous_ref=None):
        workflow = CertificateWorkflow()
        workflow.challenge_created(f"designate://fake/{policy_id}")
        workflow.certificate_stored(f"barbican://fake/{policy_id}")
        workflow.apply_consumer(previous_ref)
        workflow.probe(True)
        workflow.challenge_cleaned()
        self.providers.certificate_refs[policy_id] = workflow.candidate_ref
        return workflow

    def rotation(self, policy_id: str, active_ref: str, consumers: set[str]):
        workflow = RotationWorkflow(1, active_ref, consumers={name: active_ref for name in consumers})
        workflow.candidate_created(f"barbican://fake/{policy_id}/v2", expected_revision=1)
        for consumer in consumers:
            workflow.consumer_updated(consumer)
        workflow.begin_verification(consumers)
        workflow.verified(True)
        self.providers.rotation_refs[policy_id] = workflow.active_ref
        return workflow

    def tags(self, resource_id: str, desired: dict[str, str]):
        return TagReconciler().reconcile(self.providers.tag_adapter, resource_id, desired)
