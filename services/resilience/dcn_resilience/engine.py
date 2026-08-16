from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .contracts import EventClient, OperationClient
from .store import Journal
from .workflows import DevelopmentAdapter, WORKFLOWS, compensation


class Engine:
    def __init__(self, journal: Journal, operations: OperationClient, events: EventClient, adapter: DevelopmentAdapter):
        self.journal, self.operations, self.events, self.adapter = journal, operations, events, adapter
        self.worker_id = str(uuid.uuid4())

    def submit(self, kind: str, project_id: str, idempotency_key: str, request: dict[str, Any]) -> dict[str, Any]:
        if kind not in WORKFLOWS:
            raise ValueError("unsupported workflow")
        if not project_id or not idempotency_key:
            raise ValueError("project and idempotency key are required")
        request = dict(request)
        request["project_id"] = project_id
        operation_id = request.get("operation_id", str(uuid.uuid4()))
        try:
            operation_id = str(uuid.UUID(operation_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("operation_id must be a canonical UUID") from exc
        record, created = self.journal.create({
            "id": operation_id, "project_id": project_id, "kind": kind,
            "idempotency_key": idempotency_key, "correlation_id": str(uuid.uuid4()), "request": request,
        })
        if not created and record["request"] != request:
            raise ValueError("idempotency key reused with a different request")
        return self.run(record["id"], project_id)

    def run(self, operation_id: str, project_id: str) -> dict[str, Any]:
        record = self.journal.get(operation_id, project_id)
        if record["state"] == "succeeded":
            return record
        if not self.journal.acquire_lease(operation_id, self.worker_id):
            raise RuntimeError("operation is leased by another worker")
        self.journal.set_state(operation_id, "running")
        self._transition(operation_id, "RUNNING", {"kind": record["kind"]})
        completed = self.journal.completed_steps(operation_id)
        try:
            steps = WORKFLOWS[record["kind"]](record["request"], self.adapter)
            for ordinal, (name, action) in enumerate(steps):
                if name in completed:
                    continue
                if not self.journal.renew_lease(operation_id, self.worker_id):
                    raise RuntimeError("operation lease lost")
                evidence = action()
                self.journal.step_done(operation_id, ordinal, name, evidence)
                completed.add(name)
            result = {"evidence_retained": True, "completed_steps": sorted(completed)}
            self.journal.set_state(operation_id, "succeeded", result)
            self._transition(operation_id, "SUCCEEDED", result)
            self._event(record, "succeeded")
        except Exception as exc:
            compensation_evidence = []
            try:
                compensation_evidence = compensation(record["kind"], self.adapter, record["request"], completed)
            except Exception as compensation_error:
                compensation_evidence = [{"error": str(compensation_error), "manual_action_required": True}]
            result = {"error": str(exc), "compensation": compensation_evidence}
            self.journal.set_state(operation_id, "failed", result)
            self._transition(operation_id, "FAILED", result)
            self._event(record, "failed")
        finally:
            self.journal.release_lease(operation_id, self.worker_id)
        return self.journal.get(operation_id, project_id)

    def _transition(self, operation_id: str, state: str, detail: dict[str, Any]) -> None:
        try:
            self.operations.transition(operation_id, state, detail)
        except Exception:
            # Cross-track evidence is durable in the delivery journal. A target
            # outage must not roll back an otherwise valid resilience workflow.
            return

    def _event(self, record: dict[str, Any], outcome: str) -> None:
        envelope = {
            "contract_version": "track-b.event.v1alpha1", "event_id": str(uuid.uuid4()),
            "event_type": "resource.changed", "occurred_at": datetime.now(UTC).isoformat(),
            "domain_id": record["request"].get("domain_id", "default"),
            "project_id": record["project_id"],
            "actor_id": record["request"].get("requested_by", "track-c-controller"),
            "resource": {"type": record["kind"], "id": record["id"]},
            "severity": "INFO" if outcome == "succeeded" else "ERROR",
            "operation_id": record["id"], "correlation_id": record["correlation_id"],
            "request_id": record["request"].get("request_id", record["correlation_id"]),
            "payload": {"action": f"{record['kind']}.{outcome}", "outcome": outcome},
        }
        try:
            self.events.emit("resource.changed", envelope)
        except Exception:
            # The Track B delivery has its own checkpoint/DLQ lifecycle.
            return
