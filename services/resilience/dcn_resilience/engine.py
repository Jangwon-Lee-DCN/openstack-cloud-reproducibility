from __future__ import annotations

import uuid
from typing import Any

from .contracts import EventClient, OperationClient
from .store import Journal
from .workflows import DevelopmentAdapter, WORKFLOWS, compensation


class Engine:
    def __init__(self, journal: Journal, operations: OperationClient, events: EventClient, adapter: DevelopmentAdapter):
        self.journal, self.operations, self.events, self.adapter = journal, operations, events, adapter

    def submit(self, kind: str, project_id: str, idempotency_key: str, request: dict[str, Any]) -> dict[str, Any]:
        if kind not in WORKFLOWS:
            raise ValueError("unsupported workflow")
        if not project_id or not idempotency_key:
            raise ValueError("project and idempotency key are required")
        request = dict(request)
        request["project_id"] = project_id
        operation_id = str(uuid.uuid4())
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
        self.journal.set_state(operation_id, "running")
        self.operations.transition(operation_id, "running", {"kind": record["kind"]})
        completed = self.journal.completed_steps(operation_id)
        try:
            steps = WORKFLOWS[record["kind"]](record["request"], self.adapter)
            for ordinal, (name, action) in enumerate(steps):
                if name in completed:
                    continue
                evidence = action()
                self.journal.step_done(operation_id, ordinal, name, evidence)
                completed.add(name)
            result = {"evidence_retained": True, "completed_steps": sorted(completed)}
            self.journal.set_state(operation_id, "succeeded", result)
            self.operations.transition(operation_id, "succeeded", result)
            self._event(record, "succeeded")
        except Exception as exc:
            compensation_evidence = []
            try:
                compensation_evidence = compensation(record["kind"], self.adapter, record["request"], completed)
            except Exception as compensation_error:
                compensation_evidence = [{"error": str(compensation_error), "manual_action_required": True}]
            result = {"error": str(exc), "compensation": compensation_evidence}
            self.journal.set_state(operation_id, "failed", result)
            self.operations.transition(operation_id, "failed", result)
            self._event(record, "failed")
        return self.journal.get(operation_id, project_id)

    def _event(self, record: dict[str, Any], outcome: str) -> None:
        self.events.emit(f"{record['kind']}.{outcome}", {
            "project_id": record["project_id"], "correlation_id": record["correlation_id"],
            "operation_id": record["id"], "deduplication_key": f"{record['id']}:{outcome}",
        })
