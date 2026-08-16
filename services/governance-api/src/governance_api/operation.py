from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4


CONTRACT_VERSION = "track-a.operation.v1alpha1"
STATES = frozenset({"REQUESTED", "VALIDATING", "SCHEDULED", "RUNNING",
                    "ROLLING_BACK", "SUCCEEDED", "FAILED", "CANCELLED"})


@dataclass(frozen=True)
class OperationRef:
    contract_version: str
    id: str
    project_id: str
    region_id: str
    action: str
    target_type: str
    target_id: str | None
    fingerprint: str
    idempotency_key: str
    state: str
    progress: int
    current_step: str | None
    error: dict | None
    correlation_id: str
    created_at: str
    updated_at: str
    lease_owner: str | None
    lease_expires_at: str | None
    attempt: int
    next_attempt_at: str | None
    checkpoint: dict | None
    request: dict

    def as_contract(self) -> dict:
        return asdict(self)


class FakeOperationClient:
    """Exact canonical consumer fake; never a second production task DB."""

    def create(self, *, action: str, idempotency_key: str, request_id: str,
               project_id: str = "00000000-0000-0000-0000-000000000000",
               region_id: str = "RegionOne", target_type: str = "governance_resource",
               target_id: str | None = None) -> OperationRef:
        request = {"request_id": request_id}
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        timestamp = datetime.now(UTC).isoformat()
        return OperationRef(
            CONTRACT_VERSION, str(uuid4()), project_id, region_id, action, target_type,
            target_id, fingerprint, idempotency_key, "REQUESTED", 0, None, None,
            str(uuid4()), timestamp, timestamp, None, None, 0, None, None, request)
