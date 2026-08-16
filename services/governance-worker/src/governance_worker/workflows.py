from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class WorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class QueueEnvelope:
    resource_id: str
    project_id: str
    operation_id: str
    request_id: str
    revision: int

    def __post_init__(self):
        if self.revision < 1 or not all((self.resource_id, self.project_id, self.operation_id, self.request_id)):
            raise WorkflowError("queue envelope requires IDs and a positive revision")


@dataclass
class BudgetEvaluator:
    emitted: set[tuple[str, str, int]] = field(default_factory=set)

    def evaluate(self, *, budget_id: str, period: str, amount: Decimal,
                 spend: Decimal, thresholds: list[int]) -> list[int]:
        if amount <= 0 or spend < 0:
            raise WorkflowError("invalid budget amounts")
        percent = (spend / amount) * 100
        events = []
        for threshold in sorted(set(thresholds)):
            key = (budget_id, period, threshold)
            if percent >= threshold and key not in self.emitted:
                self.emitted.add(key)
                events.append(threshold)
        return events


class CertificatePhase(StrEnum):
    PENDING = "pending_authorization"
    CHALLENGE = "dns_challenge"
    STORED = "stored_in_barbican"
    APPLYING = "applying_consumer"
    ACTIVE = "active"
    FAILED = "failed"


@dataclass
class CertificateWorkflow:
    phase: CertificatePhase = CertificatePhase.PENDING
    challenge_ref: str | None = None
    candidate_ref: str | None = None
    previous_ref: str | None = None
    cleanup_required: bool = False

    def challenge_created(self, challenge_ref: str):
        self._require(CertificatePhase.PENDING)
        self.challenge_ref = challenge_ref
        self.cleanup_required = True
        self.phase = CertificatePhase.CHALLENGE

    def certificate_stored(self, barbican_ref: str):
        self._require(CertificatePhase.CHALLENGE)
        if not barbican_ref.startswith("barbican://"):
            raise WorkflowError("certificate material must be referenced through Barbican")
        self.candidate_ref = barbican_ref
        self.phase = CertificatePhase.STORED

    def apply_consumer(self, previous_ref: str | None):
        self._require(CertificatePhase.STORED)
        self.previous_ref = previous_ref
        self.phase = CertificatePhase.APPLYING

    def probe(self, healthy: bool):
        self._require(CertificatePhase.APPLYING)
        self.phase = CertificatePhase.ACTIVE if healthy else CertificatePhase.FAILED

    def challenge_cleaned(self):
        self.challenge_ref = None
        self.cleanup_required = False

    def rollback_ref(self) -> str | None:
        return self.previous_ref if self.phase == CertificatePhase.FAILED else None

    def compensation_actions(self) -> list[dict[str, str]]:
        if self.phase != CertificatePhase.FAILED:
            return []
        actions = []
        if self.previous_ref:
            actions.append({"action": "restore_consumer", "secret_ref": self.previous_ref})
        if self.candidate_ref:
            actions.append({"action": "retire_candidate", "secret_ref": self.candidate_ref})
        if self.challenge_ref:
            actions.append({"action": "delete_dns_challenge", "challenge_ref": self.challenge_ref})
        return actions

    def _require(self, phase):
        if self.phase != phase:
            raise WorkflowError(f"expected {phase}, found {self.phase}")


class RotationPhase(StrEnum):
    CANDIDATE_PENDING = "candidate_pending"
    UPDATING = "updating_consumers"
    VERIFYING = "verifying"
    ACTIVE = "active"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


@dataclass
class RotationWorkflow:
    revision: int
    active_ref: str
    phase: RotationPhase = RotationPhase.CANDIDATE_PENDING
    candidate_ref: str | None = None
    consumers: dict[str, str] = field(default_factory=dict)
    original_consumers: dict[str, str] = field(default_factory=dict)
    updated_consumers: set[str] = field(default_factory=set)

    def fence(self, expected_revision: int):
        if expected_revision != self.revision:
            raise WorkflowError("rotation revision conflict")

    def candidate_created(self, ref: str, *, expected_revision: int):
        self.fence(expected_revision)
        if self.phase != RotationPhase.CANDIDATE_PENDING or not ref.startswith("barbican://"):
            raise WorkflowError("invalid rotation candidate")
        self.candidate_ref = ref
        self.original_consumers = dict(self.consumers)
        self.phase = RotationPhase.UPDATING

    def consumer_updated(self, name: str):
        if self.phase != RotationPhase.UPDATING or not self.candidate_ref:
            raise WorkflowError("rotation is not updating consumers")
        self.consumers[name] = self.candidate_ref
        self.updated_consumers.add(name)

    def begin_verification(self, required_consumers: set[str]):
        if self.phase != RotationPhase.UPDATING:
            raise WorkflowError("rotation is not updating consumers")
        if not required_consumers.issubset(self.updated_consumers):
            self.phase = RotationPhase.ROLLING_BACK
            return
        self.phase = RotationPhase.VERIFYING

    def verified(self, healthy: bool):
        if self.phase != RotationPhase.VERIFYING:
            raise WorkflowError("rotation is not verifying")
        if healthy:
            self.active_ref = self.candidate_ref or self.active_ref
            self.revision += 1
            self.phase = RotationPhase.ACTIVE
        else:
            self.phase = RotationPhase.ROLLING_BACK

    def rollback(self):
        if self.phase != RotationPhase.ROLLING_BACK:
            raise WorkflowError("rotation is not rolling back")
        self.consumers = dict(self.original_consumers)
        self.candidate_ref = None
        self.phase = RotationPhase.ROLLED_BACK

    def compensation_actions(self) -> list[dict[str, str]]:
        if self.phase != RotationPhase.ROLLING_BACK:
            return []
        actions = [{"action": "restore_consumer", "consumer": name, "secret_ref": ref}
                   for name, ref in sorted(self.original_consumers.items())]
        if self.candidate_ref:
            actions.append({"action": "revoke_candidate", "secret_ref": self.candidate_ref})
        return actions
