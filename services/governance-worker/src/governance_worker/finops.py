from __future__ import annotations

import json
from datetime import UTC, datetime
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4


@dataclass(frozen=True)
class Budget:
    budget_id: str
    domain_id: str
    project_id: str
    period: str
    amount: Decimal
    thresholds: tuple[int, ...] = (50, 80, 90, 100)


@dataclass
class DeterministicBudgetEvents:
    keys: set[tuple[str, str, int]] = field(default_factory=set)
    events: list[dict] = field(default_factory=list)

    def emit(self, budget: Budget, threshold: int, spend: Decimal) -> bool:
        key = (budget.budget_id, budget.period, threshold)
        if key in self.keys:
            return False
        self.keys.add(key)
        self.events.append({"event_type": "budget.threshold", "project_id": budget.project_id,
                            "budget_id": budget.budget_id, "period": budget.period,
                            "threshold": threshold, "spend": str(spend),
                            "amount": str(budget.amount)})
        return True


class SQLiteBudgetEvents:
    def __init__(self, store):
        self.store = store

    def emit(self, budget: Budget, threshold: int, spend: Decimal) -> bool:
        event_id, outbox_id = str(uuid4()), str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        payload = {"event_id": event_id, "event_type": "budget.threshold",
                   "domain_id": budget.domain_id, "project_id": budget.project_id,
                   "resource_type": "budget", "resource_id": budget.budget_id,
                   "payload": {"period": budget.period, "threshold": threshold,
                               "spend": str(spend), "amount": str(budget.amount)}}
        with self.store.transaction() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO budget_events VALUES(?,?,?,?,?,?,?,?)",
                (budget.budget_id, budget.project_id, budget.period, threshold,
                 str(spend), str(budget.amount), outbox_id, created_at))
            if cursor.rowcount != 1:
                return False
            db.execute("INSERT INTO outbox VALUES(?,?,?,?,?,'pending',0,?,NULL,NULL,NULL,?)",
                       (outbox_id, budget.project_id, "budget.threshold",
                        f"budget:{budget.budget_id}:{budget.period}:{threshold}",
                        self.store.encode(payload), created_at, created_at))
        return True


class BudgetReconciler:
    def __init__(self, repository):
        self.repository = repository

    def evaluate(self, budget: Budget, spend: Decimal) -> list[int]:
        if budget.amount <= 0 or spend < 0:
            raise ValueError("invalid budget or spend")
        percent = spend / budget.amount * 100
        emitted = []
        for threshold in sorted(set(budget.thresholds)):
            if percent >= threshold and self.repository.emit(budget, threshold, spend):
                emitted.append(threshold)
        return emitted


class PostgresBudgetEvents:
    """Insert threshold state and notification outbox atomically."""

    def __init__(self, connection):
        self.connection = connection

    def emit(self, budget: Budget, threshold: int, spend: Decimal) -> bool:
        event_id, outbox_id = str(uuid4()), str(uuid4())
        payload = {"event_id": event_id, "event_type": "budget.threshold",
                   "domain_id": budget.domain_id, "project_id": budget.project_id,
                   "resource_type": "budget", "resource_id": budget.budget_id,
                   "payload": {"period": budget.period, "threshold": threshold,
                               "spend": str(spend), "amount": str(budget.amount)}}
        with self.connection.transaction():
            outbox_cursor = self.connection.execute(
                """INSERT INTO governance_outbox
                   (id,project_id,event_type,dedup_key,payload,status,attempts,available_at,created_at)
                   VALUES (%s,%s,'budget.threshold',%s,%s::jsonb,'pending',0,now(),now())
                   ON CONFLICT(project_id,dedup_key) DO NOTHING""",
                (outbox_id, budget.project_id,
                 f"budget:{budget.budget_id}:{budget.period}:{threshold}",
                 json.dumps(payload, sort_keys=True, separators=(",", ":"))))
            if outbox_cursor.rowcount != 1:
                return False
            cursor = self.connection.execute(
                """INSERT INTO governance_budget_event
                   (event_id,domain_id,project_id,budget_id,period,threshold,spend,amount,outbox_id,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT(budget_id,period,threshold) DO NOTHING""",
                (event_id, budget.domain_id, budget.project_id, budget.budget_id,
                 budget.period, threshold, spend, budget.amount, outbox_id))
            if cursor.rowcount != 1:
                self.connection.execute("DELETE FROM governance_outbox WHERE id=%s", (outbox_id,))
                return False
        return True
