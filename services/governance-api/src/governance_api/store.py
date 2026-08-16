from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock


SCHEMA_VERSION = 1


class Store:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._migrate()

    def _migrate(self):
        self.connection.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
        INSERT INTO schema_version(version) SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
        CREATE TABLE IF NOT EXISTS resources(
          kind TEXT NOT NULL, id TEXT NOT NULL, domain_id TEXT NOT NULL,
          project_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          body TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(kind,id)
        );
        CREATE INDEX IF NOT EXISTS resources_scope ON resources(kind,project_id,updated_at,id);
        CREATE TABLE IF NOT EXISTS idempotency(
          project_id TEXT NOT NULL, action TEXT NOT NULL, key TEXT NOT NULL,
          response TEXT NOT NULL, PRIMARY KEY(project_id,action,key)
        );
        CREATE TABLE IF NOT EXISTS audit_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
          project_id TEXT NOT NULL, occurred_at TEXT NOT NULL, body TEXT NOT NULL,
          previous_hash TEXT NOT NULL, integrity_hash TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS audit_scope ON audit_events(project_id,seq);
        """)
        self.connection.commit()

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    @staticmethod
    def encode(value) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def decode(value: str):
        return json.loads(value)
