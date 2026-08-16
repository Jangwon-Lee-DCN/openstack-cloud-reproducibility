"""Versioned Track A/B consumer contracts and deterministic development fakes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

OPERATION_CONTRACT = "dcn.operations/v1alpha1"
EVENT_CONTRACT = "dcn.events/v1alpha1"


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
        self.transitions.append({"operation_id": operation_id, "state": state, "detail": detail})


@dataclass
class FakeEventClient:
    contract_version: str = EVENT_CONTRACT
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, event_type: str, envelope: dict[str, Any]) -> None:
        required = {"project_id", "correlation_id", "operation_id", "deduplication_key"}
        missing = required - envelope.keys()
        if missing:
            raise ValueError(f"event envelope missing {sorted(missing)}")
        self.events.append({"type": event_type, "envelope": envelope})
