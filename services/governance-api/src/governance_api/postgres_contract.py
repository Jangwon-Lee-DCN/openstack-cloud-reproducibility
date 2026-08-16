from __future__ import annotations

from contextlib import contextmanager
from typing import Protocol


TENANT_SCOPE_SQL = "SELECT set_config('dcn.project_id', %s, true)"
OUTBOX_CLAIM_SQL = """
WITH candidates AS (
  SELECT id FROM governance_outbox
  WHERE ((status IN ('pending','retry') AND available_at <= now())
      OR (status = 'leased' AND lease_until < now()))
  ORDER BY created_at,id
  FOR UPDATE SKIP LOCKED
  LIMIT %s
)
UPDATE governance_outbox AS outbox
SET status='leased', lease_owner=%s, lease_until=now() + (%s * interval '1 second')
FROM candidates WHERE outbox.id=candidates.id
RETURNING outbox.id,outbox.project_id,outbox.event_type,outbox.payload,outbox.attempts
"""


class DBAPIConnection(Protocol):
    def cursor(self): ...
    def commit(self): ...
    def rollback(self): ...


class PostgreSQLSessionContract:
    """Driver-neutral transaction and tenant/RLS contract; owns no credentials."""

    def __init__(self, connection: DBAPIConnection):
        self.connection = connection

    @contextmanager
    def tenant_transaction(self, project_id: str):
        cursor = self.connection.cursor()
        try:
            cursor.execute(TENANT_SCOPE_SQL, (project_id,))
            yield cursor
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def claim_outbox(self, cursor, owner: str, limit: int, lease_seconds: int):
        cursor.execute(OUTBOX_CLAIM_SQL, (limit, owner, lease_seconds))
        return cursor.fetchall()
