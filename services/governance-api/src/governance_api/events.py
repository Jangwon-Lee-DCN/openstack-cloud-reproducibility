from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


CONTRACT_VERSION = "track-b.event.v1alpha1"


def resource_changed_event(ctx, operation, resource_type: str, resource_id: str,
                           request_id: str, action: str) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "event_id": str(uuid4()),
        "event_type": "resource.changed",
        "occurred_at": datetime.now(UTC).isoformat(),
        "domain_id": ctx.domain_id,
        "project_id": ctx.project_id,
        "actor_id": ctx.user_id,
        "resource": {"type": resource_type, "id": resource_id},
        "severity": "INFO",
        "operation_id": operation.id,
        "correlation_id": operation.correlation_id,
        "request_id": request_id,
        "payload": {"action": action},
    }
