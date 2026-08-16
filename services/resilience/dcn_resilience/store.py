"""SQLite operation journal; safe to reopen after controller restart."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS operations (
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
              idempotency_key TEXT NOT NULL, correlation_id TEXT NOT NULL,
              state TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
              UNIQUE(project_id, kind, idempotency_key)
            );
            CREATE TABLE IF NOT EXISTS steps (
              operation_id TEXT NOT NULL, ordinal INTEGER NOT NULL, name TEXT NOT NULL,
              state TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '{}',
              PRIMARY KEY(operation_id, name),
              FOREIGN KEY(operation_id) REFERENCES operations(id) ON DELETE CASCADE
            );
            """
        )

    def create(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        try:
            self.db.execute(
                "INSERT INTO operations(id,project_id,kind,idempotency_key,correlation_id,state,request_json) VALUES(?,?,?,?,?,?,?)",
                (record["id"], record["project_id"], record["kind"], record["idempotency_key"],
                 record["correlation_id"], "requested", json.dumps(record["request"], sort_keys=True)),
            )
            self.db.commit()
            return self.get(record["id"], record["project_id"]), True
        except sqlite3.IntegrityError:
            # Clear the failed INSERT transaction before the lookup. Leaving it
            # open holds SQLite locks and can stall a restarted controller.
            self.db.rollback()
            row = self.db.execute(
                "SELECT id FROM operations WHERE project_id=? AND kind=? AND idempotency_key=?",
                (record["project_id"], record["kind"], record["idempotency_key"]),
            ).fetchone()
            return self.get(row["id"], record["project_id"]), False

    def get(self, operation_id: str, project_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM operations WHERE id=? AND project_id=?", (operation_id, project_id)
        ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        result["result"] = json.loads(result.pop("result_json"))
        result["steps"] = [dict(step) for step in self.db.execute(
            "SELECT ordinal,name,state,evidence_json FROM steps WHERE operation_id=? ORDER BY ordinal", (operation_id,)
        )]
        for step in result["steps"]:
            step["evidence"] = json.loads(step.pop("evidence_json"))
        return result

    def set_state(self, operation_id: str, state: str, result: dict[str, Any] | None = None) -> None:
        self.db.execute("UPDATE operations SET state=?, result_json=? WHERE id=?",
                        (state, json.dumps(result or {}, sort_keys=True), operation_id))
        self.db.commit()

    def step_done(self, operation_id: str, ordinal: int, name: str, evidence: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO steps VALUES(?,?,?,?,?) ON CONFLICT(operation_id,name) DO UPDATE SET state=excluded.state,evidence_json=excluded.evidence_json",
            (operation_id, ordinal, name, "succeeded", json.dumps(evidence, sort_keys=True)),
        )
        self.db.commit()

    def completed_steps(self, operation_id: str) -> set[str]:
        return {row[0] for row in self.db.execute(
            "SELECT name FROM steps WHERE operation_id=? AND state='succeeded'", (operation_id,)
        )}
