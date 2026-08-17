"""Track C resources, schedulers and deterministic controller loops."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .adapters import DeterministicServiceFake, development_catalog
from .engine import Engine
from .policies import image_attestation_gate, retention_decision

COLLECTIONS = {
    "backup-policies", "backup-runs", "restore-drills", "protection-groups", "dr-plans",
    "dr-executions", "network-diagnostics", "maintenance-campaigns", "image-products",
    "image-builds", "image-revocations",
}


class ResourceStore:
    def __init__(self, connection: sqlite3.Connection):
        self.db = connection
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS resources(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, project_id TEXT NOT NULL,
          spec_json TEXT NOT NULL, status_json TEXT NOT NULL, generation INTEGER NOT NULL,
          created_at REAL NOT NULL, updated_at REAL NOT NULL,
          UNIQUE(kind,project_id,id))""")
        self.db.commit()

    def create(self, kind: str, project_id: str, spec: dict[str, Any], resource_id: str | None = None,
               now: float | None = None) -> dict[str, Any]:
        self._kind(kind)
        timestamp = time.time() if now is None else now
        resource_id = resource_id or str(uuid.uuid4())
        self.db.execute("INSERT INTO resources VALUES(?,?,?,?,?,?,?,?)", (
            resource_id, kind, project_id, json.dumps(spec, sort_keys=True),
            json.dumps({"phase": "pending"}), 1, timestamp, timestamp))
        self.db.commit()
        return self.get(kind, project_id, resource_id)

    def get(self, kind: str, project_id: str, resource_id: str) -> dict[str, Any]:
        self._kind(kind)
        row = self.db.execute("SELECT * FROM resources WHERE kind=? AND project_id=? AND id=?",
                              (kind, project_id, resource_id)).fetchone()
        if row is None:
            raise KeyError(resource_id)
        return self._decode(row)

    def list(self, kind: str, project_id: str, limit: int = 50, marker: str | None = None) -> dict[str, Any]:
        self._kind(kind)
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        params: list[Any] = [kind, project_id]
        clause = ""
        if marker:
            marker_row = self.db.execute("SELECT created_at,id FROM resources WHERE kind=? AND project_id=? AND id=?",
                                         (kind, project_id, marker)).fetchone()
            if marker_row is None:
                raise ValueError("invalid marker")
            clause = " AND (created_at > ? OR (created_at = ? AND id > ?))"
            params.extend([marker_row["created_at"], marker_row["created_at"], marker])
        params.append(limit + 1)
        rows = list(self.db.execute(
            f"SELECT * FROM resources WHERE kind=? AND project_id=?{clause} ORDER BY created_at,id LIMIT ?", params))
        more = len(rows) > limit
        items = [self._decode(row) for row in rows[:limit]]
        return {"items": items, "next_marker": items[-1]["id"] if more else None}

    def update(self, kind: str, project_id: str, resource_id: str, spec: dict[str, Any],
               expected_generation: int) -> dict[str, Any]:
        cursor = self.db.execute(
            "UPDATE resources SET spec_json=?,generation=generation+1,updated_at=? WHERE kind=? AND project_id=? AND id=? AND generation=?",
            (json.dumps(spec, sort_keys=True), time.time(), kind, project_id, resource_id, expected_generation))
        self.db.commit()
        if cursor.rowcount != 1:
            raise ValueError("generation conflict")
        return self.get(kind, project_id, resource_id)

    def set_status(self, kind: str, project_id: str, resource_id: str, status: dict[str, Any]) -> dict[str, Any]:
        cursor = self.db.execute("UPDATE resources SET status_json=?,updated_at=? WHERE kind=? AND project_id=? AND id=?",
                                 (json.dumps(status, sort_keys=True), time.time(), kind, project_id, resource_id))
        self.db.commit()
        if cursor.rowcount != 1:
            raise KeyError(resource_id)
        return self.get(kind, project_id, resource_id)

    def delete(self, kind: str, project_id: str, resource_id: str) -> None:
        current = self.get(kind, project_id, resource_id)
        if current["status"].get("phase") in {"running", "deleting"}:
            raise ValueError("running resource cannot be deleted")
        self.db.execute("DELETE FROM resources WHERE kind=? AND project_id=? AND id=?",
                        (kind, project_id, resource_id))
        self.db.commit()

    def _decode(self, row) -> dict[str, Any]:
        value = dict(row)
        value["spec"] = json.loads(value.pop("spec_json"))
        value["status"] = json.loads(value.pop("status_json"))
        return value

    @staticmethod
    def _kind(kind: str) -> None:
        if kind not in COLLECTIONS:
            raise ValueError("unsupported resource collection")


@dataclass
class Controller:
    store: ResourceStore
    engine: Engine
    providers: dict[str, DeterministicServiceFake]
    platform_owner: str = "platform-images"

    def reconcile(self, kind: str, project_id: str, resource_id: str) -> dict[str, Any]:
        resource = self.store.get(kind, project_id, resource_id)
        if resource["status"].get("phase") == "succeeded":
            return resource
        self.store.set_status(kind, project_id, resource_id, {"phase": "running"})
        try:
            result = getattr(self, f"_reconcile_{kind.replace('-', '_')}")(resource)
            return self.store.set_status(kind, project_id, resource_id, {"phase": "succeeded", **result})
        except Exception as exc:
            return self.store.set_status(kind, project_id, resource_id,
                                         {"phase": "failed", "reason": str(exc), "retryable": True})

    def tick(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        reconciled = []
        for kind in ("backup-policies", "dr-plans", "network-diagnostics", "maintenance-campaigns",
                     "image-builds", "image-revocations"):
            rows = self.store.db.execute("SELECT id,project_id,status_json,spec_json FROM resources WHERE kind=?", (kind,))
            for row in rows:
                status, spec = json.loads(row["status_json"]), json.loads(row["spec_json"])
                due = kind != "backup-policies" or (spec.get("enabled", True) and status.get("next_run_at", 0) <= now)
                if due and status.get("phase") in {"pending", "scheduled", "failed"}:
                    self.reconcile(kind, row["project_id"], row["id"])
                    reconciled.append(row["id"])
        return reconciled

    def _run(self, workflow: str, resource: dict[str, Any], request: dict[str, Any] | None = None):
        operation = self.engine.submit(workflow, resource["project_id"],
                                       f"{resource['kind']}:{resource['id']}:g{resource['generation']}",
                                       request or resource["spec"])
        if operation["state"] != "succeeded":
            raise RuntimeError(f"{workflow} operation failed: {operation['id']}")
        return operation

    def _reconcile_backup_policies(self, resource):
        spec = resource["spec"]
        interval = int(spec.get("interval_seconds", 86400))
        if interval < 60:
            raise ValueError("backup interval must be at least 60 seconds")
        run = self.store.create("backup-runs", resource["project_id"], {"policy_id": resource["id"], **spec})
        operation = self._run("backup-run", run, spec)
        self.store.set_status("backup-runs", resource["project_id"], run["id"],
                              {"phase": operation["state"], "operation_id": operation["id"]})
        generations = self.store.list("backup-runs", resource["project_id"], 200)["items"]
        retention = retention_decision([
            {"id": item["id"], "completed_at": item["updated_at"], "state": item["status"].get("phase"),
             "legal_hold": item["spec"].get("legal_hold", False),
             "restore_reference": item["spec"].get("restore_reference", False)} for item in generations
        ], int(spec.get("keep_last", 1)))
        return {"phase": "scheduled", "last_run_id": run["id"],
                "next_run_at": time.time() + interval, "retention": retention}

    def _reconcile_dr_plans(self, resource):
        execution = self.store.create("dr-executions", resource["project_id"], {"plan_id": resource["id"], **resource["spec"]})
        operation = self._run("dr-execution", execution, resource["spec"])
        self.store.set_status("dr-executions", resource["project_id"], execution["id"],
                              {"phase": operation["state"], "operation_id": operation["id"]})
        return {"last_execution_id": execution["id"], "operation_id": operation["id"]}

    def _reconcile_network_diagnostics(self, resource):
        operation = self._run("network-diagnostic", resource)
        return {"operation_id": operation["id"], "verdict": "reachable" if operation["state"] == "succeeded" else "indeterminate"}

    def _reconcile_maintenance_campaigns(self, resource):
        operation = self._run("maintenance", resource)
        return {"operation_id": operation["id"], "outcome": operation["state"]}

    def _reconcile_image_builds(self, resource):
        spec = resource["spec"]
        gate = image_attestation_gate(spec, self.platform_owner, set(spec.get("revoked_digests", [])))
        if not gate["allowed"]:
            raise ValueError(f"attestation rejected: {gate['reason_codes']}")
        operation = self._run("image-promotion", resource, spec)
        self.providers["glance"].execute("promote", resource["id"], {"operation_id": operation["id"]})
        return {"operation_id": operation["id"], "promotion": "official"}

    def _reconcile_image_revocations(self, resource):
        digest = resource["spec"].get("artifact_digest", "")
        if not digest.startswith("sha256:"):
            raise ValueError("revocation requires immutable artifact digest")
        evidence = self.providers["glance"].execute("deactivate", resource["id"], {"artifact_digest": digest})
        return {"revoked": True, "provider_evidence": evidence}


def make_controller(engine: Engine) -> Controller:
    return Controller(ResourceStore(engine.journal.db), engine, development_catalog())
