from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re

from .store import Store


def utc_now() -> datetime:
    return datetime.now(UTC)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class OutboxItem:
    id: str
    project_id: str
    event_type: str
    payload: dict
    attempts: int


class OutboxRepository:
    def __init__(self, store: Store, *, clock=utc_now):
        self.store = store
        self.clock = clock

    def claim(self, owner: str, *, limit=10, lease_seconds=30) -> list[OutboxItem]:
        current = self.clock()
        until = current + timedelta(seconds=lease_seconds)
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT id,project_id,event_type,payload,attempts FROM outbox "
                "WHERE ((status IN ('pending','retry') AND available_at<=?) "
                "OR (status='leased' AND lease_until<?)) ORDER BY created_at,id LIMIT ?",
                (stamp(current), stamp(current), limit),
            ).fetchall()
            for row in rows:
                db.execute("UPDATE outbox SET status='leased',lease_owner=?,lease_until=? WHERE id=?",
                           (owner, stamp(until), row[0]))
        return [OutboxItem(row[0], row[1], row[2], self.store.decode(row[3]), row[4]) for row in rows]

    def complete(self, item_id: str, owner: str) -> None:
        with self.store.transaction() as db:
            cursor = db.execute(
                "UPDATE outbox SET status='delivered',lease_owner=NULL,lease_until=NULL,last_error=NULL "
                "WHERE id=? AND status='leased' AND lease_owner=?", (item_id, owner))
            if cursor.rowcount != 1:
                raise RuntimeError("outbox lease was lost")

    def fail(self, item_id: str, owner: str, error_code: str, *, max_attempts=5) -> str:
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", error_code):
            error_code = "delivery_failed"
        with self.store.transaction() as db:
            row = db.execute("SELECT attempts FROM outbox WHERE id=? AND status='leased' AND lease_owner=?",
                             (item_id, owner)).fetchone()
            if not row:
                raise RuntimeError("outbox lease was lost")
            attempts = row[0] + 1
            state = "dead" if attempts >= max_attempts else "retry"
            delay = min(300, 2 ** attempts)
            db.execute(
                "UPDATE outbox SET status=?,attempts=?,available_at=?,lease_owner=NULL,lease_until=NULL,last_error=? WHERE id=?",
                (state, attempts, stamp(self.clock() + timedelta(seconds=delay)), error_code, item_id),
            )
        return state

    def status(self, item_id: str) -> str:
        row = self.store.connection.execute("SELECT status FROM outbox WHERE id=?", (item_id,)).fetchone()
        return row[0] if row else "missing"
