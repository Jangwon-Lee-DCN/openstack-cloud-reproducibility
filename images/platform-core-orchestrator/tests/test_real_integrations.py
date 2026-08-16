import json
import unittest

from core.adapters import InstanceProvisioner, ProviderError
from core.auth import IdentityVerifier
from core.openstack import CinderAdapter, NeutronAdapter, NovaAdapter, OpenStackSession
from core.reconciler import ASGResourceProvider, AutoScalingReconciler
from core.store import Store
from core.service import CoreService
import os
import tempfile
import uuid
from datetime import datetime, timezone


class KeystoneOPAContractTests(unittest.TestCase):
    def test_project_scoped_token_and_opa_allow(self):
        calls = []
        def transport(method, url, headers, body=None):
            calls.append((method, url, body))
            if "auth/tokens" in url:
                return 200, {}, {"token": {"project": {"id": "p1"}, "user": {"id": "u1"},
                                                  "roles": [{"name": "member"}]}}
            return 200, {"X-Request-Id": "decision-1"}, {"result": {"allow": True, "policy_version": "v4"}}
        verifier = IdentityVerifier("keystone-opa", keystone_url="http://keystone/v3",
                                    opa_url="http://opa/v1/data/vpc/authz/decision", transport=transport)
        claims = verifier.verify({"X-Auth-Token": "token", "X-DCN-Authorization-Class": "project-write"})
        self.assertEqual(claims["project_id"], "p1")
        self.assertEqual(claims["opa_decision_id"], "decision-1")
        self.assertEqual(json.loads(calls[1][2])["input"]["context"]["authorization_class"], "project-write")

    def test_invalid_token_fails_closed_without_opa(self):
        verifier = IdentityVerifier("keystone-opa", keystone_url="http://keystone/v3", opa_url="http://opa",
                                    transport=lambda *args: (401, {}, {}))
        with self.assertRaisesRegex(Exception, "Keystone rejected"):
            verifier.verify({"X-Auth-Token": "bad"})


class RealProviderContractTests(unittest.TestCase):
    def test_asg_checkpoint_survives_crash_and_protection_blocks_scale_in(self):
        fd, path = tempfile.mkstemp(); os.close(fd)
        project, user = str(uuid.uuid4()), str(uuid.uuid4())
        class CrashOnce:
            crashed = False
            deleted = False
            def provision_member(self, operation_id, spec, checkpoint, callback):
                if not self.crashed:
                    self.crashed = True; callback({"port_id": "port-resumed"}); raise RuntimeError("simulated crash")
                self.assert_checkpoint = checkpoint
                completed = checkpoint | {"server_id": "server-resumed"}; callback(completed); return completed
            def delete_member(self, checkpoint): self.deleted = True
        provider = CrashOnce()
        try:
            store, service = Store(path), CoreService(Store(path), b"s" * 32)
            template = service.create_template(project, user, {"name": "crash", "version": {"image_id": "i", "flavor_id": "f", "subnet_id": "s"}})
            group = service.create_asg(project, {"region_id": "r", "launch_template_id": template["id"], "min_size": 0, "desired_capacity": 1, "max_size": 1})
            reconciler = AutoScalingReconciler(store, provider)
            with self.assertRaisesRegex(RuntimeError, "simulated crash"): reconciler.reconcile_one(group["id"])
            with store.tx() as db: self.assertEqual("port-resumed", Store.row(db.execute("SELECT * FROM asg_members").fetchone())["resource_set"]["port_id"])
            self.assertEqual("ACTIVE", reconciler.reconcile_one(group["id"])["state"])
            self.assertEqual("port-resumed", provider.assert_checkpoint["port_id"])
            service.set_protection(project, user, "instance", "server-resumed", True)
            service.update_asg_capacity(project, group["id"], {"desired_capacity": 0})
            self.assertEqual("DEGRADED", reconciler.reconcile_one(group["id"])["state"])
            self.assertFalse(provider.deleted)
            service.set_protection(project, user, "instance", "server-resumed", False)
            self.assertEqual("ACTIVE", reconciler.reconcile_one(group["id"])["state"])
            self.assertTrue(provider.deleted)
        finally: os.unlink(path)

    def test_asg_retry_reuses_reserved_member(self):
        fd, path = tempfile.mkstemp(); os.close(fd)
        project, user = str(uuid.uuid4()), str(uuid.uuid4())
        class RetryOnce:
            calls = 0
            def provision_member(self, operation_id, spec, checkpoint, callback):
                self.calls += 1
                if self.calls == 1: raise ProviderError("NOVA_TIMEOUT", retryable=True)
                completed = {"port_id": "p", "server_id": "s"}; callback(completed); return completed
            def delete_member(self, checkpoint): pass
        try:
            store, service, provider = Store(path), CoreService(Store(path), b"s" * 32), RetryOnce()
            template = service.create_template(project, user, {"name": "retry", "version": {"image_id": "i", "flavor_id": "f", "subnet_id": "s"}})
            group = service.create_asg(project, {"region_id": "r", "launch_template_id": template["id"], "min_size": 0, "desired_capacity": 1, "max_size": 1})
            reconciler = AutoScalingReconciler(store, provider)
            self.assertEqual("SCALING", reconciler.reconcile_one(group["id"])["state"])
            with store.tx() as db:
                member_id = db.execute("SELECT id FROM asg_members").fetchone()[0]
                db.execute("UPDATE asg_members SET next_retry_at='2000-01-01T00:00:00+00:00'")
            self.assertEqual("ACTIVE", reconciler.reconcile_one(group["id"])["state"])
            with store.tx() as db:
                self.assertEqual(member_id, db.execute("SELECT id FROM asg_members").fetchone()[0])
                self.assertEqual(1, db.execute("SELECT COUNT(*) FROM asg_members").fetchone()[0])
        finally: os.unlink(path)

    def test_postgres_uuid_and_timestamp_rows_are_api_serializable(self):
        ident = uuid.uuid4()
        row = Store.row({"id": ident, "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "payload_json": {}})
        self.assertEqual(str(ident), row["id"])
        self.assertEqual("2026-01-01T00:00:00+00:00", row["created_at"])
        json.dumps(row)
    def session(self, fail_service=None):
        resources, calls = {}, []
        def transport(method, url, headers, body):
            calls.append((method, url))
            if url.endswith("/auth/tokens"):
                return 201, {"X-Subject-Token": "token"}, {"token": {"project": {"id": "project-1"}}}
            service = next(name for name in ("nova", "neutron", "cinder") if name in url)
            if fail_service == service and method == "POST": return 400, {}, {}
            if method == "DELETE": return 204, {}, {}
            if service == "neutron": payload = {"port": {"id": "port-1"}}
            elif service == "cinder": payload = {"volume": {"id": "volume-1"}}
            else: payload = {"server": {"id": "server-1"}}
            return 202 if service == "nova" else 201, {}, payload
        session = OpenStackSession("http://keystone/v3", "user", "password", "project", endpoints={
            "nova": "http://nova", "neutron": "http://neutron", "cinder": "http://cinder"}, transport=transport)
        return session, calls

    def test_real_provider_provisioning_uses_project_scoped_session(self):
        session, calls = self.session()
        result = InstanceProvisioner(NovaAdapter(session), NeutronAdapter(session), CinderAdapter(session)).provision(
            "operation-123", {"network": {"network_id": "net"}, "volume": {"size_gib": 1},
                              "server": {"image_id": "image", "flavor_id": "flavor"}})
        self.assertEqual(result, {"port_id": "port-1", "volume_id": "volume-1", "server_id": "server-1"})
        self.assertTrue(any(url.endswith("/auth/tokens") for _, url in calls))

    def test_failure_compensates_in_reverse_order(self):
        session, calls = self.session(fail_service="nova")
        with self.assertRaises(ProviderError):
            InstanceProvisioner(NovaAdapter(session), NeutronAdapter(session), CinderAdapter(session)).provision(
                "operation-123", {"network": {"network_id": "net"}, "volume": {"size_gib": 1},
                                  "server": {"image_id": "image", "flavor_id": "flavor"}})
        deletes = [url for method, url in calls if method == "DELETE"]
        self.assertIn("cinder", deletes[0]); self.assertIn("neutron", deletes[1])

    def test_asg_resource_sets_scale_and_compensate(self):
        fd, path = tempfile.mkstemp(); os.close(fd)
        try:
            store = Store(path)
            with store.tx() as db:
                db.execute("INSERT INTO launch_templates VALUES(?,?,?,?,?,?,?)", ("t", "p", "name", "", 1, 0, "2026-01-01"))
                db.execute("INSERT INTO launch_template_versions VALUES(?,?,?,?,?,?)", ("t", 1, '{"image_id":"i","flavor_id":"f","subnet_id":"s"}', "x", "u", "2026-01-01"))
                db.execute("INSERT INTO auto_scaling_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("g", "p", "r", "t", 1, 0, 1, 1, "[]", 300, "SCALING", 0, None, "2026-01-01"))
            providers = __import__('core.adapters', fromlist=['DeterministicProviders']).DeterministicProviders()
            reconciler = AutoScalingReconciler(store, ASGResourceProvider(InstanceProvisioner(providers, providers, providers)))
            result = reconciler.reconcile_all()
            self.assertEqual("ACTIVE", result[0]["state"])
            with store.tx() as db:
                member = Store.row(db.execute("SELECT * FROM asg_members").fetchone())
                db.execute("UPDATE auto_scaling_groups SET desired=0,state='SCALING' WHERE id='g'")
            self.assertTrue(member["resource_set"]["port_id"])
            reconciler.reconcile_all()
            with store.tx() as db: self.assertEqual(0, db.execute("SELECT COUNT(*) FROM asg_members").fetchone()[0])
            self.assertTrue(all(not values for values in providers.resources.values()))
        finally:
            os.unlink(path)


if __name__ == "__main__": unittest.main()
