from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock


SCHEMA_VERSION = 4


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
        CREATE TABLE IF NOT EXISTS outbox(
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL, event_type TEXT NOT NULL,
          dedup_key TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL,
          lease_owner TEXT, lease_until TEXT, last_error TEXT, created_at TEXT NOT NULL,
          UNIQUE(project_id,dedup_key)
        );
        CREATE INDEX IF NOT EXISTS outbox_ready ON outbox(status,available_at,lease_until);
        CREATE TABLE IF NOT EXISTS telemetry_checkpoints(
          source TEXT NOT NULL, project_id TEXT NOT NULL, watermark TEXT NOT NULL,
          updated_at TEXT NOT NULL, PRIMARY KEY(source,project_id)
        );
        CREATE TABLE IF NOT EXISTS usage_raw(
          project_id TEXT NOT NULL, sample_id TEXT NOT NULL, period TEXT NOT NULL,
          meter TEXT NOT NULL, quantity TEXT NOT NULL, watermark TEXT NOT NULL,
          received_at TEXT NOT NULL, PRIMARY KEY(project_id,sample_id)
        );
        CREATE TABLE IF NOT EXISTS cost_ledger(
          entry_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, sample_id TEXT NOT NULL,
          period TEXT NOT NULL, meter TEXT NOT NULL, quantity TEXT NOT NULL,
          unit_price TEXT NOT NULL, cost TEXT NOT NULL, rate_version TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(project_id,sample_id)
        );
        CREATE TABLE IF NOT EXISTS replay_nonces(
          consumer_id TEXT NOT NULL, nonce TEXT NOT NULL, expires_at TEXT NOT NULL,
          PRIMARY KEY(consumer_id,nonce)
        );
        CREATE TABLE IF NOT EXISTS canonical_events(
          event_id TEXT PRIMARY KEY, domain_id TEXT NOT NULL, project_id TEXT NOT NULL,
          idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, status TEXT NOT NULL,
          body TEXT NOT NULL, received_at TEXT NOT NULL,
          UNIQUE(project_id,idempotency_key)
        );
        CREATE INDEX IF NOT EXISTS canonical_events_scope
          ON canonical_events(project_id,status,received_at,event_id);
        """)
        self.connection.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
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
