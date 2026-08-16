import io
import json
import os
import tempfile
import threading
import unittest

from dcn_resilience.api import _scheduler_controller, build_app, openapi_document
from dcn_resilience.config import Config
from dcn_resilience.contracts import FakeEventClient, FakeOperationClient
from dcn_resilience.controlplane import COLLECTIONS, make_controller
from dcn_resilience.engine import Engine
from dcn_resilience.store import Journal
from dcn_resilience.workflows import DevelopmentAdapter


class ControlPlaneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "controlplane.db")
        self.engine = Engine(Journal(self.path), FakeOperationClient(), FakeEventClient(), DevelopmentAdapter())
        self.controller = make_controller(self.engine)

    def tearDown(self):
        self.tmp.cleanup()

    def test_crud_pagination_generation_and_project_isolation(self):
        first = self.controller.store.create("backup-policies", "project-a", {"name": "first"}, now=1)
        second = self.controller.store.create("backup-policies", "project-a", {"name": "second"}, now=2)
        self.controller.store.create("backup-policies", "project-b", {"name": "hidden"}, now=3)
        page = self.controller.store.list("backup-policies", "project-a", limit=1)
        self.assertEqual([first["id"]], [item["id"] for item in page["items"]])
        self.assertEqual(second["id"], self.controller.store.list(
            "backup-policies", "project-a", limit=1, marker=page["next_marker"])["items"][0]["id"])
        updated = self.controller.store.update("backup-policies", "project-a", first["id"],
                                               {"name": "changed"}, expected_generation=1)
        self.assertEqual(2, updated["generation"])
        with self.assertRaises(ValueError):
            self.controller.store.update("backup-policies", "project-a", first["id"], {}, 1)
        with self.assertRaises(KeyError):
            self.controller.store.get("backup-policies", "project-b", first["id"])
        self.controller.store.delete("backup-policies", "project-a", first["id"])
        with self.assertRaises(KeyError):
            self.controller.store.get("backup-policies", "project-a", first["id"])

    def test_backup_scheduler_is_repeatable_and_retention_aware(self):
        policy = self.controller.store.create("backup-policies", "project-a", {
            "name": "daily", "interval_seconds": 60, "keep_last": 1, "consistency": "crash", "enabled": True,
        })
        self.assertEqual([policy["id"]], self.controller.tick(now=1))
        current = self.controller.store.get("backup-policies", "project-a", policy["id"])
        self.assertEqual("scheduled", current["status"]["phase"])
        self.assertEqual(1, len(self.controller.store.list("backup-runs", "project-a")["items"]))
        self.controller.store.set_status("backup-policies", "project-a", policy["id"],
                                         {**current["status"], "phase": "scheduled", "next_run_at": 0})
        self.controller.tick(now=2)
        self.assertEqual(2, len(self.controller.store.list("backup-runs", "project-a")["items"]))

    def test_all_controller_loops_with_fake_providers(self):
        dr = self.controller.store.create("dr-plans", "project-a", {
            "mode": "drill", "fencing_verified": True, "approved": False})
        diagnostic = self.controller.store.create("network-diagnostics", "project-a", {
            "source_project_id": "project-a", "destination": "10.0.0.10"})
        campaign = self.controller.store.create("maintenance-campaigns", "project-a", {
            "strategy": "mixed", "instances": [], "max_unavailable": 1})
        image = self.controller.store.create("image-builds", "project-a", valid_image())
        revoke = self.controller.store.create("image-revocations", "project-a", {"artifact_digest": "sha256:artifact"})
        reconciled = set(self.controller.tick())
        self.assertEqual({dr["id"], diagnostic["id"], campaign["id"], image["id"], revoke["id"]}, reconciled)
        for kind, resource in (("dr-plans", dr), ("network-diagnostics", diagnostic),
                               ("maintenance-campaigns", campaign), ("image-builds", image),
                               ("image-revocations", revoke)):
            self.assertEqual("succeeded", self.controller.store.get(kind, "project-a", resource["id"])["status"]["phase"])
        self.assertTrue(any(call.startswith("glance.promote") for call in self.controller.providers["glance"].calls))
        self.assertTrue(any(call.startswith("glance.deactivate") for call in self.controller.providers["glance"].calls))

    def test_controller_restart_observes_completed_resource_without_duplicate_provider_call(self):
        image = self.controller.store.create("image-builds", "project-a", valid_image())
        self.controller.reconcile("image-builds", "project-a", image["id"])
        restarted_engine = Engine(Journal(self.path), FakeOperationClient(), FakeEventClient(), DevelopmentAdapter())
        restarted = make_controller(restarted_engine)
        result = restarted.reconcile("image-builds", "project-a", image["id"])
        self.assertEqual("succeeded", result["status"]["phase"])
        self.assertEqual([], restarted.providers["glance"].calls)

    def test_provider_failure_is_visible_and_retryable(self):
        revoke = self.controller.store.create("image-revocations", "project-a", {"artifact_digest": "sha256:a"})
        self.controller.providers["glance"].failures.add("deactivate")
        result = self.controller.reconcile("image-revocations", "project-a", revoke["id"])
        self.assertEqual("failed", result["status"]["phase"])
        self.assertTrue(result["status"]["retryable"])
        self.controller.providers["glance"].failures.clear()
        self.assertEqual("succeeded", self.controller.reconcile(
            "image-revocations", "project-a", revoke["id"])["status"]["phase"])

    def test_failed_operation_never_advances_external_provider(self):
        self.engine.adapter.failures.add("image.verify-signature")
        image = self.controller.store.create("image-builds", "project-a", valid_image())
        result = self.controller.reconcile("image-builds", "project-a", image["id"])
        self.assertEqual("failed", result["status"]["phase"])
        self.assertFalse(any(call.startswith("glance.promote") for call in self.controller.providers["glance"].calls))


def valid_image():
    return {
        "owner_project_id": "platform-images", "platform_owner_project_id": "platform-images",
        "image_class": "platform", "source_digest": "sha256:source", "artifact_digest": "sha256:artifact",
        "signature_verified": True, "provenance_verified": True, "test_boot_passed": True,
        "signature_ref": "oci://signature@sha256:1", "provenance_ref": "oci://provenance@sha256:2",
        "sbom_ref": "oci://sbom@sha256:3", "sbom_digest": "sha256:sbom", "critical_vulnerabilities": 0,
    }


class CrudApiE2ETest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = build_app(os.path.join(self.tmp.name, "api.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, path, method="GET", body=None, project="project-a", headers=None):
        if "?" in path:
            path, query = path.split("?", 1)
        else:
            query = ""
        payload = json.dumps(body or {}).encode()
        environ = {"PATH_INFO": path, "QUERY_STRING": query, "REQUEST_METHOD": method,
                   "CONTENT_LENGTH": str(len(payload)), "wsgi.input": io.BytesIO(payload),
                   "HTTP_X_VERIFIED_PROJECT_ID": project}
        environ.update(headers or {})
        response = {}
        def start(status, response_headers): response.update(status=status, headers=response_headers)
        raw = b"".join(self.app(environ, start))
        response["body"] = json.loads(raw) if raw else None
        return response

    def test_every_collection_has_crud_openapi_paths(self):
        document = openapi_document()
        for collection in COLLECTIONS:
            self.assertIn(f"/v1/{collection}", document["paths"])
            self.assertIn(f"/v1/{collection}/{{id}}", document["paths"])

    def test_create_list_update_get_delete(self):
        created = self.call("/v1/protection-groups", "POST", {"name": "web"})
        self.assertTrue(created["status"].startswith("201"))
        resource = created["body"]
        listed = self.call("/v1/protection-groups?limit=1")
        self.assertEqual(resource["id"], listed["body"]["items"][0]["id"])
        updated = self.call(f"/v1/protection-groups/{resource['id']}", "PUT", {"name": "api"},
                            headers={"HTTP_IF_MATCH_GENERATION": "1"})
        self.assertEqual(2, updated["body"]["generation"])
        self.assertEqual("api", self.call(f"/v1/protection-groups/{resource['id']}")["body"]["spec"]["name"])
        self.assertTrue(self.call(f"/v1/protection-groups/{resource['id']}", "DELETE")["status"].startswith("204"))

    def test_action_runs_controller(self):
        created = self.call("/v1/network-diagnostics", "POST", {
            "source_project_id": "project-a", "destination": "10.0.0.10"})["body"]
        result = self.call(f"/v1/network-diagnostics/{created['id']}/actions/reconcile", "POST")
        self.assertTrue(result["status"].startswith("202"))
        self.assertEqual("succeeded", result["body"]["status"]["phase"])


class ProductionConfigTest(unittest.TestCase):
    def test_production_mode_requires_real_credentials_and_remains_destructive_fenced(self):
        previous = dict(os.environ)
        try:
            os.environ["RESILIENCE_MODE"] = "production"
            for key in ("KEYSTONE_AUTH_URL", "KEYSTONE_APPLICATION_CREDENTIAL_ID",
                        "KEYSTONE_APPLICATION_CREDENTIAL_SECRET", "OPA_URL", "TRACK_A_URL", "TRACK_B_URL"):
                os.environ[key] = "configured"
            config = Config.from_env()
            self.assertEqual("production", config.mode)
            self.assertEqual("configured", config.integration["KEYSTONE_AUTH_URL"])
        finally:
            os.environ.clear(); os.environ.update(previous)


class SchedulerThreadTest(unittest.TestCase):
    def test_scheduler_connection_is_created_inside_owning_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            database = os.path.join(directory, "scheduler.db")
            errors = []
            def run():
                try:
                    controller = _scheduler_controller(database)
                    controller.tick(now=1)
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=run)
            worker.start(); worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual([], errors)
