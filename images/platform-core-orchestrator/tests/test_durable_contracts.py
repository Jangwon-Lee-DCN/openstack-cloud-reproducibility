import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.adapters import DeterministicProviders, InstanceProvisioner, ProviderError
from core.auth import IdentityVerifier, SignedEventVerifier
from core.errors import CoreError
from core.postgres import CLAIM_OPERATION, PUBLISH_OUTBOX
from core.service import CoreService
from core.store import Store
from core.worker import DurableWorker


class DurableContractsTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(); os.close(fd)
        self.store = Store(self.path)
        self.service = CoreService(self.store, b"x" * 32)

    def tearDown(self): os.unlink(self.path)

    def test_lease_expiry_recovery_and_stale_worker_fencing(self):
        op, _ = self.service.create_operation("p", "r", "create", "instance", {}, "lease")
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first, second = DurableWorker(self.store, "worker-a", 10), DurableWorker(self.store, "worker-b", 10)
        self.assertEqual(op["id"], first.claim(start)["id"])
        self.assertIsNone(second.claim(start + timedelta(seconds=5)))
        recovered = second.claim(start + timedelta(seconds=11))
        self.assertEqual(2, recovered["attempt"])
        self.assertFalse(first.save(op["id"], "RUNNING", "stale", {}, start + timedelta(seconds=12)))
        self.assertTrue(second.save(op["id"], "RUNNING", "nova.create", {"port_id": "port"}, start + timedelta(seconds=12)))
        self.assertTrue(second.heartbeat(op["id"], start + timedelta(seconds=13)))

    def test_retry_checkpoint_is_released_but_not_early_claimed(self):
        op, _ = self.service.create_operation("p", "r", "create", "instance", {}, "retry")
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        worker = DurableWorker(self.store, "worker", 10)
        worker.claim(start)
        self.assertTrue(worker.save(op["id"], "RUNNING", "neutron.port", {"port_id": "p"}, start, retry_after=30, release=True))
        self.assertIsNone(worker.claim(start + timedelta(seconds=29)))
        resumed = worker.claim(start + timedelta(seconds=31))
        self.assertEqual({"port_id": "p"}, resumed["checkpoint"])

    def test_provider_compensation_is_reverse_order_and_idempotent(self):
        providers = DeterministicProviders(fail_at="server")
        provisioner = InstanceProvisioner(providers, providers, providers)
        with self.assertRaises(ProviderError):
            provisioner.provision("op", {"network": {}, "volume": {"size": 1}})
        self.assertEqual(["create:port", "create:volume", "create:server", "delete:volume", "delete:port"], providers.calls)
        self.assertTrue(all(not value for value in providers.resources.values()))
        provisioner.compensate({"port_id": "port-op", "volume_id": "volume-op"})

    def test_provider_resume_reuses_deterministic_resource(self):
        providers = DeterministicProviders()
        provisioner = InstanceProvisioner(providers, providers, providers)
        checkpoint = provisioner.provision("op", {"network": {}})
        replay = provisioner.provision("op", {"network": {}}, checkpoint)
        self.assertEqual(checkpoint, replay)
        self.assertEqual(1, len(providers.resources["ports"])); self.assertEqual(1, len(providers.resources["servers"]))

    def test_retryable_provider_failure_preserves_checkpoint(self):
        providers = DeterministicProviders()
        provisioner = InstanceProvisioner(providers, providers, providers)
        original = providers.create_server
        def retryable(*args): raise ProviderError("NOVA_TIMEOUT", retryable=True)
        providers.create_server = retryable
        with self.assertRaises(ProviderError) as caught:
            provisioner.provision("op", {"network": {}, "volume": {"size": 1}})
        self.assertTrue(caught.exception.retryable)
        self.assertIn("port_id", caught.exception.checkpoint)
        self.assertIn("volume_id", caught.exception.checkpoint)
        self.assertTrue(providers.resources["ports"]); self.assertTrue(providers.resources["volumes"])
        providers.create_server = original
        resumed = provisioner.provision("op", {"network": {}, "volume": {"size": 1}}, caught.exception.checkpoint)
        self.assertIn("server_id", resumed)

    def test_production_identity_requires_signed_recent_opa_allow(self):
        key = b"i" * 32
        verifier = IdentityVerifier("signed-proxy", key, 60)
        claims = {"project_id": "p", "user_id": "u", "issued_at": time.time(), "opa_decision": "allow", "opa_decision_id": "decision-1"}
        token = verifier.sign(key, claims)
        self.assertEqual("p", verifier.verify({"X-DCN-Identity-Assertion": token})["project_id"])
        with self.assertRaises(CoreError): verifier.verify({"X-Project-Id": "p", "X-User-Id": "u"})
        denied = claims | {"opa_decision": "deny"}
        with self.assertRaises(CoreError): verifier.verify({"X-DCN-Identity-Assertion": verifier.sign(key, denied)})

    def test_aodh_signature_timestamp_and_replay_store(self):
        verifier = SignedEventVerifier(b"a" * 32, 60)
        body, timestamp = json.dumps({"event_id": "alarm-1"}, sort_keys=True).encode(), str(int(time.time()))
        verifier.verify(body, timestamp, verifier.sign(body, timestamp))
        with self.assertRaises(CoreError): verifier.verify(body + b"x", timestamp, verifier.sign(body, timestamp))
        self.assertTrue(self.store.accept_inbound_event("alarm-1", "aodh", datetime.now(timezone.utc).isoformat()))
        self.assertFalse(self.store.accept_inbound_event("alarm-1", "aodh", datetime.now(timezone.utc).isoformat()))

    def test_postgres_contract_uses_nonblocking_claim_and_jsonb_migration(self):
        migration = (Path(__file__).parent / ".." / "migrations" / "postgresql" / "001_core.sql").read_text(encoding="utf-8")
        self.assertIn("FOR UPDATE SKIP LOCKED", CLAIM_OPERATION)
        self.assertIn("FOR UPDATE SKIP LOCKED", PUBLISH_OUTBOX)
        self.assertIn("jsonb", migration); self.assertIn("timestamptz", migration)
        self.assertIn("UNIQUE(project_id,idempotency_key)", migration)


if __name__ == "__main__": unittest.main()
