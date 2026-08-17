import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "governance-worker" / "src"), str(ROOT / "governance-api" / "src")]

from governance_api.security import RequestContext
from governance_api.service import GovernanceService
from governance_api.store import Store
from governance_worker.audit_loki import LokiAuditExporter


class Response:
    status = 204
    def __enter__(self): return self
    def __exit__(self, *_): return False


class LokiAuditTest(unittest.TestCase):
    def test_redacted_project_label_and_checkpoint(self):
        store = Store()
        ctx = RequestContext("domain", "project-aabbccddeeff0011", "user", frozenset({"member"}))
        GovernanceService(store).append_audit(
            ctx, action="server.create", target={"type": "server", "id": "one"}, outcome="ok",
            request_id="request", changes={"password": "must-not-leak", "name": "safe"})
        payloads = []
        def send(request, timeout):
            payloads.append(json.loads(request.data))
            self.assertEqual(request.headers["X-scope-orgid"], "openstack")
            return Response()
        exporter = LokiAuditExporter("http://loki")
        with patch("governance_worker.audit_loki.urlopen", side_effect=send):
            self.assertEqual(exporter.export(store), 1)
            self.assertEqual(exporter.export(store), 0)
        stream = payloads[0]["streams"][0]
        self.assertEqual(stream["stream"]["openstack_project_id"], ctx.project_id)
        self.assertNotIn("must-not-leak", stream["values"][0][1])
        self.assertTrue(GovernanceService(store).verify_audit_chain())


if __name__ == "__main__": unittest.main()
