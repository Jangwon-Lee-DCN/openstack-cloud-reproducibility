import unittest

from governance_api.audit_fixture import DevelopmentAuditSigner, SignedAuditFixture
from governance_api.errors import Forbidden, GovernanceError
from governance_api.security import RequestContext
from governance_api.service import GovernanceService
from governance_api.store import Store


class AuditFixtureTest(unittest.TestCase):
    def setUp(self):
        self.service = GovernanceService(Store())
        self.signer = DevelopmentAuditSigner("nova", b"development-audit-key")
        self.fixture = SignedAuditFixture(self.service, {"nova": self.signer})
        self.ctx = RequestContext("d", "p", "u")

    def test_signed_ingest_and_export_detect_tampering(self):
        event = {"project_id": "p", "action": "server.create", "target": {"type": "server", "id": "1"},
                 "outcome": "success", "request_id": "req-1", "changes": {"token": "must-redact"}}
        self.fixture.ingest(self.ctx, "nova", event, self.signer.sign(event))
        payload, manifest = self.fixture.export(self.ctx, self.signer)
        self.assertTrue(self.fixture.verify_export(payload, manifest, self.signer))
        self.assertNotIn(b"must-redact", payload)
        self.assertFalse(self.fixture.verify_export(payload + b"x", manifest, self.signer))

    def test_bad_signature_and_cross_project_are_rejected(self):
        event = {"project_id": "other", "action": "x", "target": {}, "outcome": "denied", "request_id": "r"}
        with self.assertRaises(GovernanceError):
            self.fixture.ingest(self.ctx, "nova", event, "bad")
        with self.assertRaises(Forbidden):
            self.fixture.ingest(self.ctx, "nova", event, self.signer.sign(event))


if __name__ == "__main__":
    unittest.main()
