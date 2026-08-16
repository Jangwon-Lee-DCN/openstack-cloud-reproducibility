import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from core.errors import CoreError
from core.service import CoreService
from core.store import Store


class CoreServiceTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(); os.close(fd)
        self.svc = CoreService(Store(self.path), b"x" * 32, approval_ttl=60)
        self.project, self.other = "project-a", "project-b"

    def tearDown(self):
        os.unlink(self.path)

    def assertCode(self, code, callable_):
        with self.assertRaises(CoreError) as caught: callable_()
        self.assertEqual(code, caught.exception.code)

    def test_idempotent_operation_and_collision(self):
        first, created = self.svc.create_operation(self.project, "seoul-ssu-1", "instance.create", "instance", {"x": 1}, "key")
        for _ in range(100):
            replay, replay_created = self.svc.create_operation(self.project, "seoul-ssu-1", "instance.create", "instance", {"x": 1}, "key")
            self.assertFalse(replay_created); self.assertEqual(first["id"], replay["id"])
        self.assertTrue(created)
        self.assertCode("IDEMPOTENCY_KEY_REUSED", lambda: self.svc.create_operation(self.project, "seoul-ssu-1", "instance.create", "instance", {"x": 2}, "key"))
        self.assertEqual(1, len(self.svc.operation_events(self.project, first["id"])))

    def test_project_isolation(self):
        op, _ = self.svc.create_operation(self.project, "r", "a", "instance", {}, "key")
        self.assertCode("RESOURCE_NOT_FOUND", lambda: self.svc.get_operation(self.other, op["id"]))

    def test_cancel_terminal_guard(self):
        op, _ = self.svc.create_operation(self.project, "r", "a", "instance", {}, "key")
        cancelled = self.svc.cancel_operation(self.project, op["id"])
        self.assertEqual("CANCELLED", cancelled["state"])
        self.assertCode("OPERATION_NOT_CANCELLABLE", lambda: self.svc.cancel_operation(self.project, op["id"]))

    def test_preflight_approval_is_payload_and_project_bound(self):
        payload = {"region_id": "seoul-ssu-1", "subnet_id": "subnet-a"}
        result = self.svc.preflight(self.project, "instance", payload)
        self.assertEqual("PASS", result["decision"])
        self.svc.verify_approval(result["approval_token"], self.project, payload)
        self.assertCode("PROJECT_SCOPE_MISMATCH", lambda: self.svc.verify_approval(result["approval_token"], self.other, payload))
        self.assertCode("APPROVAL_PAYLOAD_CHANGED", lambda: self.svc.verify_approval(result["approval_token"], self.project, payload | {"x": 1}))

    def test_preflight_fail_has_no_approval(self):
        result = self.svc.preflight(self.project, "instance", {})
        self.assertEqual("FAIL", result["decision"]); self.assertIsNone(result["approval_token"])

    def test_template_versions_are_append_only_and_asg_is_pinned(self):
        spec = {"image_id": "image", "flavor_id": "flavor", "subnet_id": "subnet"}
        template = self.svc.create_template(self.project, "user", {"name": "web", "version": spec})
        self.svc.add_template_version(self.project, "user", template["id"], spec | {"image_id": "image-2"})
        group = self.svc.create_asg(self.project, {"region_id": "r", "launch_template_id": template["id"], "min_size": 1, "desired_capacity": 2, "max_size": 4, "subnet_ids": ["subnet"]})
        self.svc.set_default_version(self.project, template["id"], 2)
        self.assertEqual(1, self.svc.get_asg(self.project, group["id"])["template_version"])
        self.assertEqual(2, len(self.svc.get_template(self.project, template["id"])["versions"]))

    def test_plaintext_user_data_is_forbidden(self):
        spec = {"image_id": "i", "flavor_id": "f", "subnet_id": "s", "user_data": "secret"}
        self.assertCode("PLAINTEXT_SECRET_FORBIDDEN", lambda: self.svc.create_template(self.project, "u", {"name": "bad", "version": spec}))

    def test_asg_capacity_and_event_deduplication(self):
        template = self.svc.create_template(self.project, "u", {"name": "web", "version": {"image_id": "i", "flavor_id": "f", "subnet_id": "s"}})
        group = self.svc.create_asg(self.project, {"region_id": "r", "launch_template_id": template["id"], "min_size": 1, "desired_capacity": 2, "max_size": 3, "subnet_ids": ["s"]})
        first = self.svc.scaling_event(self.project, group["id"], "alarm-1", 10)
        replay = self.svc.scaling_event(self.project, group["id"], "alarm-1", 10)
        self.assertEqual(3, first["desired_capacity"])
        self.assertEqual("alarm-1", replay["event_id"])
        self.assertEqual(3, self.svc.get_asg(self.project, group["id"])["desired"])

    def test_deletion_protection_and_restore_capability(self):
        self.svc.set_protection(self.project, "u", "instance", "server", True)
        self.assertCode("RESOURCE_PROTECTED", lambda: self.svc.recycle(self.project, "u", "instance", "server"))
        self.svc.set_protection(self.project, "u", "instance", "server", False)
        entry = self.svc.recycle(self.project, "u", "instance", "server")
        self.assertEqual("FULL", entry["restore_capability"])
        self.assertEqual("RESTORED", self.svc.restore(self.project, entry["id"])["state"])
        unknown = self.svc.recycle(self.project, "u", "network", "net")
        self.assertCode("RESTORE_NOT_SUPPORTED", lambda: self.svc.restore(self.project, unknown["id"]))

    def test_outbox_commits_with_operation(self):
        op, _ = self.svc.create_operation(self.project, "r", "a", "instance", {}, "key")
        with self.svc.store.tx() as db:
            row = db.execute("SELECT topic,aggregate_id FROM outbox").fetchone()
        self.assertEqual(("operation.requested.v1", op["id"]), tuple(row))


if __name__ == "__main__": unittest.main()
