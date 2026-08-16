import io
import json
import os
import tempfile
import unittest

from dcn_resilience.api import build_app
from dcn_resilience.contracts import FakeEventClient, FakeOperationClient
from dcn_resilience.engine import Engine
from dcn_resilience.store import Journal
from dcn_resilience.workflows import DevelopmentAdapter, maintenance_eligibility


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "journal.db")
        self.operations, self.events, self.adapter = FakeOperationClient(), FakeEventClient(), DevelopmentAdapter()
        self.engine = Engine(Journal(self.path), self.operations, self.events, self.adapter)

    def tearDown(self):
        self.tmp.cleanup()

    def submit(self, kind, body, key="key-1", project="project-a"):
        return self.engine.submit(kind, project, key, body)

    def test_backup_restore_drill_and_idempotency(self):
        body = {"targets": [{"type": "volume", "id": "vol-a"}], "consistency": "application", "guest_agent": True}
        first = self.submit("backup-run", body)
        second = self.submit("backup-run", body)
        self.assertEqual("succeeded", first["state"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(1, self.adapter.calls.count("backup.capture"))
        self.assertIn("backup.cleanup", self.adapter.calls)

    def test_backup_failure_always_thaws(self):
        self.adapter.failures.add("backup.capture")
        result = self.submit("backup-run", {"consistency": "filesystem"})
        self.assertEqual("failed", result["state"])
        self.assertIn("backup.thaw", self.adapter.calls)

    def test_restart_resumes_without_duplicate_steps(self):
        self.adapter.failures.add("backup.probe")
        result = self.submit("backup-run", {"consistency": "crash"})
        self.assertEqual("failed", result["state"])
        self.adapter.failures.clear()
        restarted = Engine(Journal(self.path), self.operations, self.events, self.adapter)
        result = restarted.run(result["id"], "project-a")
        self.assertEqual("succeeded", result["state"])
        self.assertEqual(1, self.adapter.calls.count("backup.capture"))

    def test_dr_fencing_is_fail_closed(self):
        result = self.submit("dr-execution", {"mode": "drill", "fencing_verified": False})
        self.assertEqual("failed", result["state"])
        self.assertNotIn("dr.recover-storage", self.adapter.calls)

    def test_dr_live_execution_requires_approval(self):
        result = self.submit("dr-execution", {"mode": "failover", "fencing_verified": True})
        self.assertEqual("failed", result["state"])

    def test_network_cross_project_is_rejected_and_no_probe_runs(self):
        result = self.submit("network-diagnostic", {
            "source_project_id": "project-b", "destination": "10.0.0.10"
        })
        self.assertEqual("failed", result["state"])
        self.assertNotIn("network.probe-limited", self.adapter.calls)

    def test_network_probe_is_bounded(self):
        result = self.submit("network-diagnostic", {
            "source_project_id": "project-a", "destination": "10.0.0.10", "packet_count": 4
        })
        self.assertEqual("failed", result["state"])

    def test_maintenance_constraints_block_unsafe_live_migration(self):
        body = {"strategy": "live-migrate", "instances": [{"id": "vm-gpu", "pci_passthrough": True}]}
        result = self.submit("maintenance", body)
        self.assertEqual("failed", result["state"])
        self.assertNotIn("maintenance.disable-scheduling", self.adapter.calls)
        self.assertEqual(("blocked", ["numa_pinned"]), maintenance_eligibility({"numa_pinned": True}))

    def test_maintenance_failure_restores_scheduler_state(self):
        self.adapter.failures.add("maintenance.migrate-bounded")
        result = self.submit("maintenance", {"strategy": "mixed", "instances": [], "max_unavailable": 1})
        self.assertEqual("failed", result["state"])
        self.assertIn("maintenance.restore-scheduler-state", self.adapter.calls)

    def test_image_promotion_requires_full_supply_chain(self):
        valid = {
            "source_digest": "sha256:source", "artifact_digest": "sha256:artifact",
            "signature_ref": "oci://evidence/signature@sha256:1", "sbom_ref": "oci://evidence/sbom@sha256:2",
            "provenance_ref": "oci://evidence/provenance@sha256:3", "signature_verified": True,
            "test_boot_passed": True, "critical_vulnerabilities": 0,
            "owner_project_id": "platform", "platform_owner_project_id": "platform", "image_class": "platform",
        }
        self.assertEqual("succeeded", self.submit("image-promotion", valid)["state"])
        invalid = dict(valid, owner_project_id="tenant")
        self.assertEqual("failed", self.submit("image-promotion", invalid, key="key-2")["state"])

    def test_project_scoped_lookup(self):
        result = self.submit("network-diagnostic", {"source_project_id": "project-a", "destination": "10.0.0.1"})
        with self.assertRaises(KeyError):
            self.engine.journal.get(result["id"], "project-b")

    def test_idempotency_key_payload_conflict(self):
        self.submit("network-diagnostic", {"source_project_id": "project-a", "destination": "10.0.0.1"})
        with self.assertRaises(ValueError):
            self.submit("network-diagnostic", {"source_project_id": "project-a", "destination": "10.0.0.2"})


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = build_app(os.path.join(self.tmp.name, "api.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, path, method="GET", body=None, project=None, key=None):
        payload = json.dumps(body or {}).encode()
        environ = {"PATH_INFO": path, "REQUEST_METHOD": method, "CONTENT_LENGTH": str(len(payload)),
                   "wsgi.input": io.BytesIO(payload)}
        if project:
            environ["HTTP_X_VERIFIED_PROJECT_ID"] = project
        if key:
            environ["HTTP_IDEMPOTENCY_KEY"] = key
        response = {}
        def start(status, headers):
            response["status"], response["headers"] = status, headers
        response["body"] = json.loads(b"".join(self.app(environ, start)))
        return response

    def test_health_and_fail_closed_identity(self):
        self.assertTrue(self.call("/healthz")["status"].startswith("200"))
        self.assertTrue(self.call("/v1/runs/backup-run", "POST")["status"].startswith("401"))

    def test_public_response_omits_project_and_request(self):
        response = self.call("/v1/runs/network-diagnostic", "POST", {
            "source_project_id": "project-a", "destination": "10.0.0.10"
        }, "project-a", "idem-1")
        self.assertTrue(response["status"].startswith("201"))
        self.assertNotIn("project_id", response["body"])
        self.assertNotIn("request", response["body"])


if __name__ == "__main__":
    unittest.main()
