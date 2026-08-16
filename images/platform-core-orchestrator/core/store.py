import json
import sqlite3
import threading
from contextlib import contextmanager


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, region_id TEXT NOT NULL,
 action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT,
 fingerprint TEXT NOT NULL, idempotency_key TEXT NOT NULL, state TEXT NOT NULL,
 progress INTEGER NOT NULL DEFAULT 0, current_step TEXT, error_json TEXT,
 correlation_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
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

    @staticmethod
    def row(row):
        if row is None:
            return None
        value = dict(row)
        for key in tuple(value):
            if key.endswith("_json") and value[key] is not None:
                value[key[:-5]] = json.loads(value.pop(key))
        return value
