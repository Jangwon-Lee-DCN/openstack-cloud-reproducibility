import threading
import os
import subprocess
import sys
import unittest
import urllib.request
import urllib.error
import json
from http.server import ThreadingHTTPServer

from governance_api.http import Handler
from governance_api.errors import GovernanceError
from governance_api.providers import ProviderError
from governance_api.service import GovernanceService
from governance_api.store import Store


class HttpSmokeTest(unittest.TestCase):
    @staticmethod
    def canonical_event(event_id=None):
        from uuid import uuid4
        return {
            "contract_version": "track-b.event.v1alpha1", "event_id": event_id or str(uuid4()),
            "event_type": "tag.drift.detected", "occurred_at": "2026-08-16T00:00:00Z",
            "domain_id": "d", "project_id": "p", "actor_id": "producer",
            "resource": {"type": "server", "id": str(uuid4())}, "severity": "WARNING",
            "operation_id": str(uuid4()), "correlation_id": str(uuid4()),
            "request_id": "req-track-c", "payload": {"token": "redact-me"},
        }
    def test_central_opa_transport_failure_is_fail_closed(self):
        request = type("Request", (), {})()
        request.headers = {"X-Auth-Token": "token", "X-Project-Id": "project"}
        request.command = "POST"
        request.path = "/v1/budgets"
        request.identity = type("Identity", (), {"validate": lambda self, token, project: {
            "domain_id": "domain", "project_id": project, "user_id": "user", "roles": ["member"]}})()
        request.authorizer = type("Authorizer", (), {"authorize": lambda self, value:
            (_ for _ in ()).throw(ProviderError("provider is unreachable"))})()
        with self.assertRaises(GovernanceError) as raised:
            Handler.request_context(request)
        self.assertEqual((raised.exception.status, raised.exception.code), (503, "policy_unavailable"))

    def serve(self):
        Handler.service = GovernanceService(Store())
        Handler.identity = type("Identity", (), {"validate": lambda self, token, project: {
            "domain_id": "d", "project_id": project, "user_id": "u", "roles": []}})()
        Handler.authorizer = type("Authorizer", (), {"authorize": lambda self, value: True})()
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def test_health(self):
        Handler.service = GovernanceService(Store())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"http://127.0.0.1:{server.server_port}/healthz", timeout=2) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_production_mode_fails_closed(self):
        result = subprocess.run(
            [sys.executable, "-m", "governance_api.http"],
            env=dict(os.environ, GOVERNANCE_MODE="production"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"refusing fake or production execution", result.stderr)

    def test_http_crud_flow(self):
        server, thread, opener = self.serve()
        base = f"http://127.0.0.1:{server.server_port}"
        identity = {"X-Auth-Token": "fixture", "X-Project-Id": "p",
                    "X-Openstack-Request-Id": "req", "Content-Type": "application/json"}
        try:
            create = urllib.request.Request(
                f"{base}/v1/budgets", data=b'{"amount":"10"}', method="POST",
                headers={**identity, "Idempotency-Key": "create-budget"})
            with opener.open(create) as response:
                resource = json.load(response)
            with opener.open(urllib.request.Request(f"{base}/v1/budgets?limit=1", headers=identity)) as response:
                self.assertEqual(len(json.load(response)["items"]), 1)
            update = urllib.request.Request(
                f"{base}/v1/budgets/{resource['id']}", data=b'{"amount":"12"}', method="PATCH",
                headers={**identity, "Idempotency-Key": "update-budget", "If-Match": "1"})
            with opener.open(update) as response:
                self.assertEqual(json.load(response)["revision"], 2)
            delete = urllib.request.Request(
                f"{base}/v1/budgets/{resource['id']}", method="DELETE",
                headers={**identity, "Idempotency-Key": "delete-budget", "If-Match": "2"})
            with opener.open(delete) as response:
                self.assertEqual(response.status, 204)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_canonical_event_http_create_replay_conflict_and_status(self):
        server, thread, opener = self.serve()
        base = f"http://127.0.0.1:{server.server_port}"
        headers = {"X-Auth-Token": "fixture", "X-Project-Id": "p",
                   "X-Openstack-Request-Id": "req", "Content-Type": "application/json",
                   "Idempotency-Key": "track-c-event-0001"}
        body = self.canonical_event()
        try:
            request = urllib.request.Request(f"{base}/v1/events", data=json.dumps(body).encode(),
                                             method="POST", headers=headers)
            with opener.open(request) as response:
                self.assertEqual(response.status, 201)
                accepted = json.load(response)
            with opener.open(request) as response:
                self.assertEqual(response.status, 200)
            changed = dict(body); changed["severity"] = "CRITICAL"
            conflict = urllib.request.Request(f"{base}/v1/events", data=json.dumps(changed).encode(),
                                              method="POST", headers={**headers, "Idempotency-Key": "track-c-event-0002"})
            with self.assertRaises(urllib.error.HTTPError) as raised:
                opener.open(conflict)
            self.assertEqual(raised.exception.code, 409)
            with opener.open(urllib.request.Request(
                    f"{base}/v1/events/{accepted['event_id']}", headers=headers)) as response:
                self.assertEqual(json.load(response)["status"], "accepted")
            with opener.open(urllib.request.Request(
                    f"{base}/v1/events?limit=1&status=accepted", headers=headers)) as response:
                self.assertEqual(len(json.load(response)["items"]), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
