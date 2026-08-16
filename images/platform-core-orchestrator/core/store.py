import json
import sqlite3
import threading
import uuid
from datetime import date, datetime
from contextlib import contextmanager


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, region_id TEXT NOT NULL,
 action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT,
 fingerprint TEXT NOT NULL, idempotency_key TEXT NOT NULL, state TEXT NOT NULL,
 progress INTEGER NOT NULL DEFAULT 0, current_step TEXT, error_json TEXT,
 correlation_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 lease_owner TEXT, lease_expires_at TEXT, attempt INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TEXT, checkpoint_json TEXT, request_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(project_id,idempotency_key));
CREATE TABLE IF NOT EXISTS operation_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT NOT NULL,
 event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
 FOREIGN KEY(operation_id) REFERENCES operations(id));
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL, aggregate_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL, published_at TEXT);
CREATE TABLE IF NOT EXISTS preflights (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
 fingerprint TEXT NOT NULL, decision TEXT NOT NULL, result_json TEXT NOT NULL,
 expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS launch_templates (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL,
 description TEXT NOT NULL, default_version INTEGER NOT NULL DEFAULT 1,
 deletion_protected INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 UNIQUE(project_id,name));
CREATE TABLE IF NOT EXISTS launch_template_versions (
 template_id TEXT NOT NULL, version INTEGER NOT NULL, spec_json TEXT NOT NULL,
 checksum TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(template_id,version),
 FOREIGN KEY(template_id) REFERENCES launch_templates(id));
CREATE TABLE IF NOT EXISTS auto_scaling_groups (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, region_id TEXT NOT NULL,
 template_id TEXT NOT NULL, template_version INTEGER NOT NULL,
 min_size INTEGER NOT NULL, desired INTEGER NOT NULL, max_size INTEGER NOT NULL,
 subnet_ids_json TEXT NOT NULL, cooldown_seconds INTEGER NOT NULL,
 state TEXT NOT NULL, deletion_protected INTEGER NOT NULL DEFAULT 0,
 last_scaled_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scaling_events (
  event_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, adjustment INTEGER NOT NULL,
  accepted INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inbound_events (
 event_id TEXT PRIMARY KEY, source TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dead_letters (
 operation_id TEXT PRIMARY KEY, reason TEXT NOT NULL, checkpoint_json TEXT NOT NULL,
 failed_at TEXT NOT NULL, FOREIGN KEY(operation_id) REFERENCES operations(id));
CREATE TABLE IF NOT EXISTS asg_members (
 id TEXT PRIMARY KEY, group_id TEXT NOT NULL, provider_id TEXT NOT NULL,
 state TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(group_id,provider_id),
 FOREIGN KEY(group_id) REFERENCES auto_scaling_groups(id));
CREATE TABLE IF NOT EXISTS resource_protection (
 project_id TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
 protected INTEGER NOT NULL, reason TEXT, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(project_id,resource_type,resource_id));
CREATE TABLE IF NOT EXISTS recycle_bin (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, resource_type TEXT NOT NULL,
 resource_id TEXT NOT NULL, provider_ids_json TEXT NOT NULL,
 deleted_by TEXT NOT NULL, deleted_at TEXT NOT NULL, purge_after TEXT NOT NULL,
 restore_capability TEXT NOT NULL, dependency_json TEXT NOT NULL, state TEXT NOT NULL);
"""


class Store:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        with self.tx() as db:
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(operations)")}
            additions = {
                "lease_owner": "TEXT", "lease_expires_at": "TEXT",
                "attempt": "INTEGER NOT NULL DEFAULT 0", "next_attempt_at": "TEXT",
                "checkpoint_json": "TEXT", "request_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE operations ADD COLUMN {name} {definition}")

    @contextmanager
    def tx(self):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=30, isolation_level="IMMEDIATE")
            db.row_factory = sqlite3.Row
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    def claim_operation(self, worker_id, lease_seconds, current_time, lease_until):
        """Atomically claim one runnable operation; expired leases are recoverable."""
        with self.tx() as db:
            row = db.execute(
                "SELECT id FROM operations WHERE state IN ('REQUESTED','VALIDATING','SCHEDULED','RUNNING','ROLLING_BACK') "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=?) "
                "AND (lease_expires_at IS NULL OR lease_expires_at<=?) ORDER BY created_at LIMIT 1",
                (current_time, current_time),
            ).fetchone()
            if not row:
                return None
            changed = db.execute(
                "UPDATE operations SET lease_owner=?,lease_expires_at=?,attempt=attempt+1,updated_at=? "
                "WHERE id=? AND (lease_expires_at IS NULL OR lease_expires_at<=?)",
                (worker_id, lease_until, current_time, row[0], current_time),
            ).rowcount
            if changed != 1:
                return None
            return self.row(db.execute("SELECT * FROM operations WHERE id=?", (row[0],)).fetchone())

    def heartbeat(self, operation_id, worker_id, current_time, lease_until):
        with self.tx() as db:
            changed = db.execute(
                "UPDATE operations SET lease_expires_at=?,updated_at=? WHERE id=? AND lease_owner=? AND lease_expires_at>?",
                (lease_until, current_time, operation_id, worker_id, current_time),
            ).rowcount
            return changed == 1

    def checkpoint(self, operation_id, worker_id, state, step, checkpoint, current_time, next_attempt_at=None, release=False):
        with self.tx() as db:
            owner, expiry = (None, None) if release else (worker_id, db.execute("SELECT lease_expires_at FROM operations WHERE id=?", (operation_id,)).fetchone()[0])
            changed = db.execute(
                "UPDATE operations SET state=?,current_step=?,checkpoint_json=?,updated_at=?,next_attempt_at=?,lease_owner=?,lease_expires_at=? "
                "WHERE id=? AND lease_owner=?",
                (state, step, json.dumps(checkpoint, sort_keys=True), current_time, next_attempt_at, owner, expiry, operation_id, worker_id),
            ).rowcount
            if changed:
                event = json.dumps({"state": state, "step": step, "checkpoint": checkpoint}, sort_keys=True)
                db.execute("INSERT INTO operation_events(operation_id,event_type,payload_json,created_at) VALUES(?,?,?,?)", (operation_id, "operation.transition", event, current_time))
            return changed == 1

    def accept_inbound_event(self, event_id, source, received_at):
        with self.tx() as db:
            try:
                db.execute("INSERT INTO inbound_events VALUES(?,?,?)", (event_id, source, received_at))
                return True
            except sqlite3.IntegrityError:
                return False

    def dead_letter(self, operation_id, reason, checkpoint, failed_at):
        with self.tx() as db:
            db.execute("INSERT OR REPLACE INTO dead_letters VALUES(?,?,?,?)", (operation_id, reason, json.dumps(checkpoint, sort_keys=True), failed_at))
            db.execute("UPDATE operations SET state='FAILED',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?", (failed_at, operation_id))
            db.execute("INSERT INTO outbox(topic,aggregate_id,payload_json,created_at) VALUES(?,?,?,?)", ("operation.dead-lettered.v1", operation_id, json.dumps({"reason": reason}, sort_keys=True), failed_at))

    def list_dead_letters(self):
        with self.tx() as db:
            return [self.row(row) for row in db.execute("SELECT * FROM dead_letters ORDER BY failed_at")]

    @staticmethod
    def row(row):
        if row is None:
            return None
        value = dict(row)
        for key, raw in tuple(value.items()):
            if isinstance(raw, uuid.UUID): value[key] = str(raw)
            elif isinstance(raw, (datetime, date)): value[key] = raw.isoformat()
        for key in tuple(value):
            if key.endswith("_json"):
                raw = value.pop(key)
                value[key[:-5]] = (json.loads(raw) if isinstance(raw, str) else raw) if raw is not None else None
        return value


def store_from_env(environ):
    database_url = environ.get("CORE_DATABASE_URL")
    if database_url:
        from .postgres_store import PostgresStore
        return PostgresStore(database_url)
    if environ.get("CORE_RUNTIME_MODE", "production") != "development":
        raise RuntimeError("CORE_DATABASE_URL is required outside development mode")
    return Store(environ.get("CORE_DB_PATH", "/data/core.db"))
