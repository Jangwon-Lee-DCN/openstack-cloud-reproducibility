import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from core.adapters import DeterministicProviders, InstanceProvisioner, ProviderError
from core.reconciler import ASGResourceProvider, AutoScalingReconciler
from core.service import CoreService
from core.store import Store
from core.worker import DurableWorker
from core.worker_main import main as worker_main


class CompleteFakeE2E(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(); os.close(fd)
        self.store, self.project = Store(self.path), "00000000-0000-0000-0000-000000000001"
        self.service = CoreService(self.store, b"s" * 32)
        self.providers = DeterministicProviders()

    def tearDown(self): os.unlink(self.path)

    def template(self, name="web"):
        return self.service.create_template(self.project, "00000000-0000-0000-0000-000000000002", {"name": name, "version": {"image_id": "image", "flavor_id": "flavor", "subnet_id": "subnet"}})

    def test_worker_end_to_end_timeline_and_restart_safe_checkpoint(self):
        op, _ = self.service.create_operation(self.project, "seoul-ssu-1", "instance.create", "instance", {"network": {}, "volume": {"size": 1}}, "e2e")
        result = DurableWorker(self.store, "worker-1").execute_once(InstanceProvisioner(self.providers, self.providers, self.providers))
        self.assertEqual("succeeded", result["outcome"])
        self.assertEqual("SUCCEEDED", self.service.get_operation(self.project, op["id"])["state"])
        self.assertEqual(["operation.requested", "operation.transition", "operation.transition"], [event["event_type"] for event in self.service.operation_events(self.project, op["id"])])
        self.assertIsNone(DurableWorker(self.store, "worker-after-restart").claim())

    def test_retry_backoff_then_dead_letter(self):
        class TimeoutProviders(DeterministicProviders):
            def create_server(self, operation_id, spec): raise ProviderError("NOVA_TIMEOUT", retryable=True)
        providers = TimeoutProviders()
        op, _ = self.service.create_operation(self.project, "r", "instance.create", "instance", {"network": {}}, "retry")
        worker = DurableWorker(self.store, "worker", lease_seconds=5, max_attempts=2)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first = worker.execute_once(InstanceProvisioner(providers, providers, providers), start)
        self.assertEqual({"operation_id": op["id"], "outcome": "retry", "retry_after": 1}, first)
        self.assertIsNone(worker.execute_once(InstanceProvisioner(providers, providers, providers), start + timedelta(milliseconds=500)))
        second = worker.execute_once(InstanceProvisioner(providers, providers, providers), start + timedelta(seconds=2))
        self.assertEqual("dead-letter", second["outcome"])
        self.assertEqual(op["id"], self.store.list_dead_letters()[0]["operation_id"])
        self.assertTrue(all(not resources for resources in providers.resources.values()))

    def test_template_pagination_asg_crud_reconcile_and_cooldown(self):
        templates = [self.template(f"web-{index}") for index in range(3)]
        first = self.service.list_templates(self.project, 2)
        second = self.service.list_templates(self.project, 2, first["next_marker"])
        self.assertEqual(2, len(first["items"])); self.assertEqual(1, len(second["items"]))
        group = self.service.create_asg(self.project, {"region_id": "r", "launch_template_id": templates[0]["id"], "min_size": 0, "desired_capacity": 2, "max_size": 3, "subnet_ids": ["s"], "cooldown_seconds": 300})
        reconciler = AutoScalingReconciler(self.store, ASGResourceProvider(InstanceProvisioner(self.providers, self.providers, self.providers)))
        self.assertEqual(2, reconciler.reconcile_one(group["id"])["actual"])
        self.service.update_asg_capacity(self.project, group["id"], {"desired_capacity": 1})
        self.assertEqual(1, reconciler.reconcile_one(group["id"])["actual"])
        event = self.service.scaling_event(self.project, group["id"], "alarm-1", 1)
        self.assertTrue(event["accepted"])
        cooldown = self.service.scaling_event(self.project, group["id"], "alarm-2", 1)
        self.assertEqual("cooldown", cooldown["reason"])

    def test_preflight_listing_protection_recycle_restore_and_privileged_purge(self):
        preflight = self.service.preflight(self.project, "instance", {"region_id": "r", "subnet_id": "s"})
        self.assertEqual(preflight["id"], self.service.get_preflight(self.project, preflight["id"])["id"])
        self.assertEqual(1, len(self.service.list_preflights(self.project)["items"]))
        template = self.template()
        self.service.set_protection(self.project, "u", "launch_template", template["id"], False)
        self.assertFalse(bool(self.service.get_protection(self.project, "launch_template", template["id"])["protected"]))
        entry = self.service.delete_template(self.project, "u", template["id"])
        restored = self.service.restore(self.project, entry["id"])
        self.assertEqual("RESTORED", restored["state"])
        retained = self.service.recycle(self.project, "u", "instance", "server")
        with self.assertRaises(Exception): self.service.purge(self.project, retained["id"], False)
        self.assertEqual("PURGED", self.service.purge(self.project, retained["id"], True)["state"])

    def test_production_worker_fails_closed_without_real_adapters(self):
        previous = os.environ.pop("CORE_RUNTIME_MODE", None)
        try:
            with self.assertRaisesRegex(RuntimeError, "refusing production worker startup"): worker_main()
        finally:
            if previous is not None: os.environ["CORE_RUNTIME_MODE"] = previous


if __name__ == "__main__": unittest.main()
