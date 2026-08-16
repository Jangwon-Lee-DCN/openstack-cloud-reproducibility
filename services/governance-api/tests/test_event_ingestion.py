import json
import unittest
from pathlib import Path
from uuid import uuid4

from governance_api.errors import Conflict, Forbidden, GovernanceError
from governance_api.errors import NotFound
from governance_api.event_ingestion import EVENT_SCHEMA
from governance_api.security import RequestContext
from governance_api.service import GovernanceService
from governance_api.store import Store


def event(project="project", domain="domain", event_id=None, payload=None):
    return {
        "contract_version": "track-b.event.v1alpha1", "event_id": event_id or str(uuid4()),
        "event_type": "tag.drift.detected", "occurred_at": "2026-08-16T00:00:00Z",
        "domain_id": domain, "project_id": project, "actor_id": "producer",
        "resource": {"type": "server", "id": str(uuid4())}, "severity": "WARNING",
        "operation_id": str(uuid4()), "correlation_id": str(uuid4()), "request_id": "req-test",
        "payload": payload or {"drift": "owner"},
    }


class CanonicalEventIngestionTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.service = GovernanceService(self.store)
        self.ctx = RequestContext("domain", "project", "user", frozenset({"member"}))

    def ingest(self, body, key="event-key-0001"):
        return self.service.ingest_canonical_event(
            self.ctx, body, key=key, request_id="req-http", encoded_size=len(json.dumps(body).encode()))

    def test_runtime_schema_is_canonical_file(self):
        canonical = json.loads((Path(__file__).parents[1] / "contracts" / "track-b" /
                                "track-b.event.v1alpha1.schema.json").read_text())
        self.assertEqual(EVENT_SCHEMA, canonical)

    def test_transactional_ingest_redaction_outbox_and_audit(self):
        body = event(payload={"token": "must-not-persist", "nested": {"ok": True}})
        record, replayed = self.ingest(body)
        self.assertFalse(replayed)
        self.assertEqual(record["event"]["payload"]["token"], "[REDACTED]")
        outbox = self.store.connection.execute("SELECT payload,status FROM outbox").fetchone()
        self.assertEqual(outbox[1], "pending")
        self.assertNotIn("must-not-persist", outbox[0])
        audit = self.store.connection.execute("SELECT body FROM audit_events").fetchone()[0]
        self.assertIn("canonical_event.ingest", audit)
        self.assertTrue(self.service.verify_audit_chain())

    def test_event_and_key_replay_are_200_semantics_but_conflicts_are_409(self):
        body = event()
        first, replayed = self.ingest(body)
        second, replayed = self.ingest(body)
        self.assertTrue(replayed)
        self.assertEqual(first, second)
        same_event_new_key, replayed = self.ingest(body, "event-key-0002")
        self.assertTrue(replayed)
        self.assertEqual(first, same_event_new_key)
        changed = dict(body); changed["severity"] = "CRITICAL"
        with self.assertRaises(Conflict):
            self.ingest(changed, "event-key-0003")
        with self.assertRaises(Conflict):
            self.ingest(event(), "event-key-0001")

    def test_scope_schema_and_bounds_fail_closed(self):
        with self.assertRaises(Forbidden):
            self.ingest(event(project="other"))
        invalid = event(); invalid["extra"] = True
        with self.assertRaises(GovernanceError):
            self.ingest(invalid)
        with self.assertRaises(GovernanceError):
            self.ingest(event(payload={"value": "x" * 16_385}))

    def test_status_pagination_and_project_isolation(self):
        one, _ = self.ingest(event(), "event-key-0001")
        self.ingest(event(), "event-key-0002")
        page = self.service.page_canonical_events(self.ctx, limit=1, status="accepted")
        self.assertEqual(len(page["items"]), 1)
        self.assertIsNotNone(page["next"])
        self.assertEqual(len(self.service.page_canonical_events(
            self.ctx, limit=1, cursor=page["next"])["items"]), 1)
        self.assertEqual(self.service.get_canonical_event(self.ctx, one["event_id"]), one)
        with self.assertRaises(NotFound):
            self.service.get_canonical_event(
                RequestContext("domain", "other", "system", frozenset({"admin"})), one["event_id"])
