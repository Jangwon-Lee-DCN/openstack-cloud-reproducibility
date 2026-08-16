import json
import os
import tempfile
import unittest

from dcn_resilience.adapters import development_catalog
from dcn_resilience.contracts import EVENT_CONTRACT, OPERATION_CONTRACT, FakeEventClient
from dcn_resilience.policies import (
    dr_objectives, explain_network_path, image_attestation_gate,
    maintenance_action, retention_decision, validate_restore_evidence,
)
from dcn_resilience.store import Journal


class AdapterContractTest(unittest.TestCase):
    def test_all_required_openstack_ports_are_explicit(self):
        catalog = development_catalog()
        self.assertEqual(
            {"cinder", "glance", "manila", "rgw", "nova", "neutron", "octavia", "designate", "masakari"},
            set(catalog),
        )
        for service, adapter in catalog.items():
            self.assertEqual(service, adapter.discover("project-a")["service"])

    def test_adapter_observe_and_compensation_are_deterministic(self):
        cinder = development_catalog()["cinder"]
        evidence = cinder.execute("backup", "backup-a", {"source": "volume-a"})
        self.assertEqual(evidence["generation"], cinder.observe("backup-a")["generation"])
        compensation = cinder.compensate("backup", "backup-a", evidence)
        self.assertEqual("missing", cinder.observe("backup-a")["state"])
        self.assertEqual(evidence["generation"], compensation["evidence_generation"])

    def test_unsupported_action_fails_closed(self):
        with self.assertRaises(ValueError):
            development_catalog()["glance"].execute("delete-production", "image-a", {})


class LeaseCheckpointTest(unittest.TestCase):
    def test_lease_exclusion_expiry_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(os.path.join(directory, "journal.db"))
            operation, _ = journal.create({
                "id": "op-a", "project_id": "project-a", "kind": "backup-run",
                "idempotency_key": "key-a", "correlation_id": "trace-a", "request": {},
            })
            self.assertTrue(journal.acquire_lease(operation["id"], "worker-a", now=100))
            self.assertFalse(journal.acquire_lease(operation["id"], "worker-b", now=101))
            journal.step_done(operation["id"], 0, "capture", {"generation": "sha256:a"})
            self.assertEqual({"capture"}, journal.completed_steps(operation["id"]))
            self.assertTrue(journal.acquire_lease(operation["id"], "worker-b", now=131))
            self.assertFalse(journal.renew_lease(operation["id"], "worker-a", now=132))


class BackupPolicyTest(unittest.TestCase):
    def test_retention_preserves_hold_restore_reference_and_latest_success(self):
        generations = [
            {"id": "new", "completed_at": "2026-08-04T00:00:00Z", "state": "succeeded"},
            {"id": "running", "completed_at": "2026-08-03T00:00:00Z", "state": "running"},
            {"id": "restore", "completed_at": "2026-08-02T00:00:00Z", "state": "succeeded", "restore_reference": True},
            {"id": "hold", "completed_at": "2026-08-01T00:00:00Z", "state": "succeeded", "legal_hold": True},
            {"id": "old", "completed_at": "2026-07-01T00:00:00Z", "state": "succeeded"},
        ]
        decision = retention_decision(generations, keep_last=1)
        self.assertEqual({"new", "running", "restore", "hold"}, set(decision["keep"]))
        self.assertEqual(["old"], decision["expire"])

    def test_restore_evidence_requires_checksum_probes_and_exposes_cleanup(self):
        result = validate_restore_evidence({
            "artifact_checksum": "sha256:a", "restored_checksum": "sha256:a",
            "probes": [{"name": "mount", "result": "passed"}], "cleanup_state": "failed",
        })
        self.assertTrue(result["restorable"])
        self.assertTrue(result["manual_cleanup_required"])


class DrPolicyTest(unittest.TestCase):
    def test_rpo_rto_are_measured_from_utc_timeline(self):
        result = dr_objectives("2026-08-16T00:00:00Z", "2026-08-16T00:10:00Z",
                               "2026-08-16T00:25:00Z", 900, 1200)
        self.assertEqual(600, result["measured_rpo_seconds"])
        self.assertEqual(900, result["measured_rto_seconds"])
        self.assertTrue(result["rpo_met"] and result["rto_met"])

    def test_invalid_dr_timeline_is_not_silently_clamped(self):
        with self.assertRaises(ValueError):
            dr_objectives("2026-08-16T00:20:00Z", "2026-08-16T00:10:00Z",
                          "2026-08-16T00:25:00Z", 900, 1200)


class NetworkExplanationTest(unittest.TestCase):
    def test_first_policy_denial_is_explained_without_infrastructure_ids(self):
        result = explain_network_path({
            "source_bound": True, "sg_egress": True, "nacl_egress": False,
            "route_present": True, "nacl_ingress": True, "sg_ingress": True,
        })
        self.assertEqual("NETWORK_ACL_EGRESS_DENY", result["reason_code"])
        self.assertEqual("redacted", result["infrastructure"])
        self.assertNotIn("chassis", json.dumps(result))

    def test_declared_allowed_but_probe_failed_is_mismatch(self):
        allowed = {key: True for key in ("source_bound", "sg_egress", "nacl_egress", "route_present",
                                          "nat_ready", "lb_healthy", "nacl_ingress", "sg_ingress")}
        allowed.update({"declared_reachable": True, "probe_reachable": False})
        self.assertEqual("mismatch", explain_network_path(allowed)["verdict"])


class MaintenanceMatrixTest(unittest.TestCase):
    def test_planned_unconstrained_guest_live_migrates(self):
        self.assertEqual("live-migrate", maintenance_action({}, True, False)["action"])

    def test_pci_guest_uses_cold_alternative_but_local_disk_is_manual(self):
        self.assertEqual("cold-migrate", maintenance_action({"pci_passthrough": True}, True, False)["action"])
        self.assertEqual("manual", maintenance_action({"local_disk": True}, True, False)["action"])

    def test_masakari_lock_blocks_competing_campaign(self):
        result = maintenance_action({}, True, True)
        self.assertEqual(["MASAKARI_OPERATION_ACTIVE"], result["reason_codes"])

    def test_unplanned_non_shared_guest_requires_manual_recovery(self):
        result = maintenance_action({"shared_storage": False}, False, False)
        self.assertEqual("manual", result["action"])


class ImageAttestationTest(unittest.TestCase):
    def valid(self):
        return {"owner_project_id": "platform", "image_class": "platform",
                "artifact_digest": "sha256:artifact", "signature_verified": True,
                "provenance_verified": True, "sbom_digest": "sha256:sbom",
                "critical_vulnerabilities": 0, "test_boot_passed": True}

    def test_valid_attestation_promotes(self):
        self.assertTrue(image_attestation_gate(self.valid(), "platform", set())["allowed"])

    def test_revocation_forces_deactivation(self):
        result = image_attestation_gate(self.valid(), "platform", {"sha256:artifact"})
        self.assertFalse(result["allowed"])
        self.assertIn("REVOKED_DIGEST", result["reason_codes"])
        self.assertEqual("deactivated", result["required_glance_status"])


class CrossTrackFixtureTest(unittest.TestCase):
    def load(self, name):
        root = os.path.join(os.path.dirname(__file__), "..", "contracts")
        with open(os.path.join(root, name), encoding="utf-8") as stream:
            return json.load(stream)

    def test_track_a_fixture_matches_consumer_version(self):
        fixture = self.load("track-a-operation-v1alpha1.json")
        self.assertEqual(OPERATION_CONTRACT, fixture["apiVersion"])
        self.assertTrue({"id", "project_id", "idempotency_key", "correlation_id", "state"} <= fixture["operation"].keys())

    def test_track_b_fixture_is_accepted_by_fake_producer(self):
        fixture = self.load("track-b-event-v1alpha1.json")
        self.assertEqual(EVENT_CONTRACT, fixture["apiVersion"])
        client = FakeEventClient()
        client.emit(fixture["event"]["type"], fixture["event"]["envelope"])
        self.assertEqual(1, len(client.events))
