import threading
import os
import subprocess
import sys
import unittest
import urllib.request
import json
from http.server import ThreadingHTTPServer

from governance_api.http import Handler
from governance_api.service import GovernanceService
from governance_api.store import Store


class HttpSmokeTest(unittest.TestCase):
    def serve(self):
        Handler.service = GovernanceService(Store())
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
        self.assertIn(b"refusing production mode", result.stderr)

    def test_http_crud_flow(self):
        server, thread, opener = self.serve()
        base = f"http://127.0.0.1:{server.server_port}"
        identity = {"X-Domain-Id": "d", "X-Project-Id": "p", "X-User-Id": "u",
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


if __name__ == "__main__":
    unittest.main()
