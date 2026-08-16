import json
from contextlib import contextmanager

import psycopg

from .store import Store


class CompatRow(dict):
    def __init__(self, names, values):
        super().__init__(zip(names, values)); self._values = tuple(values)
    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else super().__getitem__(key)


class Cursor:
    def __init__(self, cursor): self.cursor = cursor
    @property
    def rowcount(self): return self.cursor.rowcount
    def _row(self, row):
        if row is None: return None
        return CompatRow([column.name for column in self.cursor.description], row)
    def fetchone(self): return self._row(self.cursor.fetchone())
    def __iter__(self):
        for row in self.cursor: yield self._row(row)


class Connection:
    def __init__(self, connection): self.connection = connection
    @staticmethod
    def sql(statement):
        statement = statement.replace("?", "%s")
        if statement.startswith("INSERT OR IGNORE INTO"):
            statement = statement.replace("INSERT OR IGNORE INTO", "INSERT INTO", 1) + " ON CONFLICT DO NOTHING"
        if statement.startswith("INSERT OR REPLACE INTO dead_letters"):
            statement = ("INSERT INTO dead_letters VALUES(%s,%s,%s,%s) ON CONFLICT(operation_id) DO UPDATE SET "
                         "reason=excluded.reason,checkpoint_json=excluded.checkpoint_json,failed_at=excluded.failed_at")
        return statement
    def execute(self, statement, args=()):
        cursor = self.connection.cursor(); cursor.execute(self.sql(statement), args); return Cursor(cursor)


class PostgresStore(Store):
    """Store contract backed by PostgreSQL; no SQLite fallback is possible."""
    def __init__(self, database_url):
        if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise RuntimeError("CORE_DATABASE_URL must be PostgreSQL")
        self.database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with self.tx() as db:
            if not db.execute("SELECT to_regclass('public.operations')").fetchone()[0]:
                raise RuntimeError("PostgreSQL schema is not migrated")

    @contextmanager
    def tx(self):
        with psycopg.connect(self.database_url) as connection:
            try:
                yield Connection(connection)
                connection.commit()
            except Exception:
                connection.rollback(); raise

    def claim_operation(self, worker_id, lease_seconds, current_time, lease_until):
        with self.tx() as db:
            row = db.execute(
                "SELECT id FROM operations WHERE state IN ('REQUESTED','VALIDATING','SCHEDULED','RUNNING','ROLLING_BACK') "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=?) AND (lease_expires_at IS NULL OR lease_expires_at<=?) "
                "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1", (current_time, current_time)).fetchone()
            if not row: return None
            changed = db.execute("UPDATE operations SET lease_owner=?,lease_expires_at=?,attempt=attempt+1,updated_at=? "
                                 "WHERE id=? AND (lease_expires_at IS NULL OR lease_expires_at<=?)",
                                 (worker_id, lease_until, current_time, row[0], current_time)).rowcount
            return self.row(db.execute("SELECT * FROM operations WHERE id=?", (row[0],)).fetchone()) if changed == 1 else None

    def accept_inbound_event(self, event_id, source, received_at):
        with self.tx() as db:
            return db.execute("INSERT INTO inbound_events VALUES(?,?,?) ON CONFLICT(event_id) DO NOTHING",
                              (event_id, source, received_at)).rowcount == 1
