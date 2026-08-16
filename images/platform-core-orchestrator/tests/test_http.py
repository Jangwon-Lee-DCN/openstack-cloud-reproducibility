import json
import os
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


class HTTPContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.db = tempfile.mkstemp(); os.close(fd)
        cls.port = "18089"
        env = os.environ | {"CORE_DB_PATH": cls.db, "CORE_RUNTIME_MODE": "development", "CORE_APPROVAL_SIGNING_KEY": "z" * 32, "CORE_AODH_EVENT_KEY": "e" * 32, "CORE_AUTH_MODE": "development", "PORT": cls.port}
        cls.proc = subprocess.Popen(["python3", "-m", "core.http"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        for _ in range(200):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/healthz", timeout=.2); break
            except Exception: time.sleep(.05)
        else:
            raise RuntimeError("server did not start: " + cls.proc.stderr.read())

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(timeout=3); cls.proc.stderr.close(); os.unlink(cls.db)

    def call(self, method, path, body=None, headers=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body or {}).encode() if method != "GET" else None, method=method, headers={"Content-Type": "application/json", "X-Project-Id": "p", "X-User-Id": "u"} | (headers or {}))
        try:
            response = urllib.request.urlopen(request); return response.status, dict(response.headers), json.load(response)
        except urllib.error.HTTPError as exc: return exc.code, dict(exc.headers), json.load(exc)

    def test_health_and_operation_contract(self):
        self.assertEqual(200, urllib.request.urlopen(f"http://127.0.0.1:{self.port}/healthz").status)
        body = {"region_id": "seoul-ssu-1", "action": "instance.create", "target_type": "instance", "payload": {"name": "vm"}}
        status, headers, created = self.call("POST", "/v1/operations", body, {"Idempotency-Key": "http-key"})
        self.assertEqual(202, status); self.assertIn("/v1/operations/", headers["Location"])
        status, headers, replay = self.call("POST", "/v1/operations", body, {"Idempotency-Key": "http-key"})
        self.assertEqual("true", headers["X-Idempotent-Replay"]); self.assertEqual(created["id"], replay["id"])
        status, _, listed = self.call("GET", "/v1/operations")
        self.assertEqual(200, status); self.assertEqual(1, len(listed["items"]))

    def test_identity_required(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/operations")
        with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(request)
        self.assertEqual(401, caught.exception.code)

    def test_revisioned_transition_replay_and_conflict_statuses(self):
        create = {"region_id": "seoul-ssu-1", "action": "producer.track-c", "target_type": "artifact", "payload": {}}
        status, _, operation = self.call("POST", "/v1/operations", create, {"Idempotency-Key": "producer-http-create"})
        self.assertEqual(202, status)
        transition = {"expected_revision": 0, "state": "VALIDATING", "progress": 10, "current_step": "validate"}
        path = f"/v1/operations/{operation['id']}/transition"
        status, headers, changed = self.call("POST", path, transition, {"Idempotency-Key": "producer-http-transition"})
        self.assertEqual(202, status); self.assertEqual(1, changed["revision"])
        status, headers, replayed = self.call("POST", path, transition, {"Idempotency-Key": "producer-http-transition"})
        self.assertEqual(200, status); self.assertEqual("true", headers["X-Idempotent-Replay"]); self.assertEqual(changed, replayed)
        status, _, error = self.call("POST", path, transition | {"progress": 11}, {"Idempotency-Key": "producer-http-transition"})
        self.assertEqual(409, status); self.assertEqual("IDEMPOTENCY_KEY_REUSED", error["error"]["code"])
        status, _, error = self.call("POST", path, transition | {"state": "SCHEDULED"}, {"Idempotency-Key": "producer-http-stale"})
        self.assertEqual(409, status); self.assertEqual("OPERATION_REVISION_CONFLICT", error["error"]["code"])


if __name__ == "__main__": unittest.main()
