from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


CONTRACT_VERSION = "track-a.operation.v1alpha1"


@dataclass(frozen=True)
class OperationRef:
    id: str
    status: str
    contract_version: str = CONTRACT_VERSION


class FakeOperationClient:
    """Versioned test adapter. It never becomes a second production task DB."""

    def create(self, *, action: str, idempotency_key: str, request_id: str) -> OperationRef:
        material = f"{action}:{idempotency_key}:{request_id}"
        return OperationRef(id=f"fake-{uuid4()}", status="validating")
