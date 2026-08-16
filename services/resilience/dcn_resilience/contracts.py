"""Versioned Track A/B consumer contracts and deterministic development fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

OPERATION_CONTRACT = "track-a.operation.v1alpha1"
EVENT_CONTRACT = "track-b.event.v1alpha1"
OPERATION_STATES = frozenset({"REQUESTED", "VALIDATING", "SCHEDULED", "RUNNING", "ROLLING_BACK",
                              "SUCCEEDED", "FAILED", "CANCELLED"})


class OperationClient(Protocol):
    contract_version: str

    def transition(self, operation_id: str, state: str, detail: dict[str, Any]) -> None: ...


class EventClient(Protocol):
    contract_version: str

    def emit(self, event_type: str, envelope: dict[str, Any]) -> None: ...


@dataclass
class FakeOperationClient:
    contract_version: str = OPERATION_CONTRACT
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def transition(self, operation_id: str, state: str, detail: dict[str, Any]) -> None:
        if state not in OPERATION_STATES:
            raise ValueError(f"non-canonical Track A state: {state}")
        self.transitions.append({"operation_id": operation_id, "state": state, "detail": detail})


@dataclass
class FakeEventClient:
    contract_version: str = EVENT_CONTRACT
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, event_type: str, envelope: dict[str, Any]) -> None:
        required = {"contract_version", "event_id", "event_type", "occurred_at", "domain_id", "project_id",
                    "actor_id", "resource", "severity", "operation_id", "correlation_id", "request_id", "payload"}
        missing = required - envelope.keys()
        if missing:
            raise ValueError(f"event envelope missing {sorted(missing)}")
        if envelope["contract_version"] != EVENT_CONTRACT or envelope["event_type"] != event_type:
            raise ValueError("non-canonical Track B event version or type")
        self.events.append({"type": event_type, "envelope": envelope})
