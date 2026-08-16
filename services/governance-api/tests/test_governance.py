import json
import unittest

from governance_api.errors import Forbidden, GovernanceError
from governance_api.operation import CONTRACT_VERSION, FakeOperationClient
from governance_api.security import RequestContext, safe_projection, validate_webhook_url
from governance_api.service import GovernanceService, webhook_signature
from governance_api.store import Store


class GovernanceTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.service = GovernanceService(self.store, FakeOperationClient(), webhook_hosts={"hooks.example.test"})
        self.a = RequestContext("domain-a", "project-a", "user-a")
        self.b = RequestContext("domain-b", "project-b", "user-b")
        self.admin = RequestContext("default", "admin", "root", frozenset({"admin"}))

    def test_track_a_contract_is_versioned(self):
        self.assertEqual(CONTRACT_VERSION, "track-a.operation.v1alpha1")

    def test_notification_idempotency_and_tenant_isolation(self):
        body = {"event_type": "operation.failed", "resource_ref": "server/1"}
        one = self.service.ingest_notification(self.a, body, key="same", request_id="req-1")
        two = self.service.ingest_notification(self.a, body, key="same", request_id="req-1")
        self.assertEqual(one["id"], two["id"])
        self.assertEqual(len(self.service.list_resources(self.a, "notification")), 1)
        self.assertEqual(self.service.list_resources(self.b, "notification"), [])
        with self.assertRaises(Forbidden):
            self.service.list_resources(self.a, "notification", project_id="project-b")

    def test_webhook_ssrf_policy_and_signature(self):
        self.assertEqual(validate_webhook_url("https://hooks.example.test/dcn", {"hooks.example.test"}),
                         "https://hooks.example.test/dcn")
        for unsafe in ("http://hooks.example.test", "https://127.0.0.1/x", "https://169.254.169.254/x"):
            with self.assertRaises(GovernanceError):
                validate_webhook_url(unsafe, {"hooks.example.test"})
        self.assertEqual(webhook_signature(b"key", "1", b"{}"), webhook_signature(b"key", "1", b"{}"))

    def test_usage_rating_is_decimal_and_idempotent(self):
        body = {"meter": "cpu", "quantity": "1.25", "unit_price": "0.1234567", "period": "2026-08"}
        first = self.service.record_usage(self.a, body, key="sample-1", request_id="req-u")
        second = self.service.record_usage(self.a, body, key="sample-1", request_id="req-u")
        self.assertEqual(first["cost"], "0.154321")
        self.assertEqual(first, second)

    def test_rate_card_requires_system_role(self):
        with self.assertRaises(Forbidden):
            self.service.create_rate_card(self.a, {"unit_price": "1"}, key="r", request_id="req")
        result = self.service.create_rate_card(self.admin, {"unit_price": "1"}, key="r", request_id="req")
        self.assertEqual(result["project_id"], "admin")

    def test_certificate_and_rotation_never_accept_secret_material(self):
        with self.assertRaises(GovernanceError):
            self.service.create_certificate_policy(
                self.a, {"domains": ["a.example"], "private_key": "NO"}, key="c", request_id="req")
        with self.assertRaises(GovernanceError):
            self.service.create_rotation_policy(
                self.a, {"secret_ref": "plaintext"}, key="s", request_id="req")
        result = self.service.create_rotation_policy(
            self.a, {"secret_ref": "barbican://uuid", "consumers": []}, key="s2", request_id="req")
        self.assertEqual(result["phase"], "candidate_pending")

    def test_audit_redaction_and_integrity(self):
        self.service.append_audit(self.a, action="test", target={"type": "server", "id": "1"},
                                  outcome="success", request_id="req", changes={"token": "leak", "name": "ok"})
        event = self.service.search_audit(self.a)[0]
        self.assertEqual(event["changes"]["token"], "[REDACTED]")
        self.assertTrue(self.service.verify_audit_chain())
        self.store.connection.execute("UPDATE audit_events SET body=replace(body,'ok','tampered')")
        self.assertFalse(self.service.verify_audit_chain())

    def test_tag_policy_reserved_and_resolution(self):
        with self.assertRaises(Forbidden):
            self.service.resolve_tags(self.a, {"system/owner": "other"}, [])
        tags = self.service.resolve_tags(self.a, {"application": "api"}, [
            {"scope": "platform", "defaults": {"environment": "dev"}, "required": ["application"]},
            {"scope": "project", "defaults": {"environment": "prod"}, "required": []},
        ])
        self.assertEqual(tags["environment"], "prod")
        self.assertEqual(tags["dcn.ssu.ac.kr/project-id"], "project-a")

    def test_sensitive_corpus_is_redacted(self):
        serialized = json.dumps(safe_projection({"password": "P", "nested": {"cookie": "C"}}))
        self.assertNotIn('"P"', serialized)
        self.assertNotIn('"C"', serialized)


if __name__ == "__main__":
    unittest.main()
