import json
import unittest

from core.adapters import InstanceProvisioner, ProviderError
from core.auth import IdentityVerifier
from core.openstack import CinderAdapter, NeutronAdapter, NovaAdapter, OpenStackSession
from core.scheduler_main import DegradedRealScheduler
from core.store import Store
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

    def test_real_scheduler_never_falls_back_to_fake_compute(self):
        fd, path = tempfile.mkstemp(); os.close(fd)
        try:
            store = Store(path)
            with store.tx() as db:
                db.execute("INSERT INTO launch_templates VALUES(?,?,?,?,?,?,?)", ("t", "p", "name", "", 1, 0, "2026-01-01"))
                db.execute("INSERT INTO launch_template_versions VALUES(?,?,?,?,?,?)", ("t", 1, "{}", "x", "u", "2026-01-01"))
                db.execute("INSERT INTO auto_scaling_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           ("g", "p", "r", "t", 1, 0, 1, 1, "[]", 300, "SCALING", 0, None, "2026-01-01"))
            result = DegradedRealScheduler(store).reconcile_all()
            self.assertEqual("DEGRADED", result[0]["state"])
            with store.tx() as db: self.assertEqual(0, db.execute("SELECT COUNT(*) FROM asg_members").fetchone()[0])
        finally:
            os.unlink(path)


if __name__ == "__main__": unittest.main()
