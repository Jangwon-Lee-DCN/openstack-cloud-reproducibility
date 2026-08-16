import json
import os
import tempfile
import unittest

from dcn_resilience.cross_track import (CircuitBreaker, DeliveryError, DurableDelivery,
                                         TrackAHttpClient, TrackBHttpClient)
from dcn_resilience.integrations import KeystoneSession
from dcn_resilience.store import Journal


ROOT = os.path.join(os.path.dirname(__file__), "..", "contracts")


def fixture(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as stream:
        return json.load(stream)


class CrossTrackClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "journal.db")
        self.session = KeystoneSession("http://keystone", "id", "secret", token="token",
                                       project_id="11111111111141118111111111111111",
                                       domain_id="22222222-2222-4222-8222-222222222222",
                                       user_id="33333333-3333-4333-8333-333333333333")

    def tearDown(self): self.tmp.cleanup()

    def test_track_a_transition_walks_canonical_states_and_replays(self):
        operation = fixture("track-a-operation-v1alpha1.json")
        operation.update({"id": "44444444-4444-4444-8444-444444444444",
                          "project_id": "11111111-1111-4111-8111-111111111111", "state": "REQUESTED",
                          "revision": 0, "progress": 0})
        calls = []

        def transport(url, method="GET", headers=None, body=None, timeout=3):
            calls.append((method, url, headers, body))
            if method == "POST":
                operation.update({"state": body["state"], "revision": body["expected_revision"] + 1,
                                  "progress": body["progress"]})
            return (202 if method == "POST" else 200), dict(operation), {}

        client = TrackAHttpClient("http://track-a", self.session, Journal(self.path),
                                  fixture("track-a.operation.v1alpha1.schema.json"), transport=transport,
                                  sleeper=lambda _: None)
        client.transition(operation["id"], "RUNNING", {"kind": "backup-run"})
        client.transition(operation["id"], "RUNNING", {"kind": "backup-run"})
        self.assertEqual(["VALIDATING", "SCHEDULED", "RUNNING"],
                         [call[3]["state"] for call in calls if call[0] == "POST"])
        self.assertTrue(all(call[2].get("X-Auth-Token") == "token" for call in calls))

    def test_track_b_scope_headers_duplicate_and_restart_checkpoint(self):
        event = fixture("track-b-event-v1alpha1.json")
        event.update({"project_id": self.session.project_id, "domain_id": self.session.domain_id})
        calls = []

        def transport(url, method="GET", headers=None, body=None, timeout=3):
            calls.append((headers, body))
            return 201, {"event": body, "status": "accepted"}, {}

        client = TrackBHttpClient("http://track-b", self.session, Journal(self.path),
                                  fixture("track-b.event.v1alpha1.schema.json"), transport=transport)
        client.emit("resource.changed", event)
        restarted = TrackBHttpClient("http://track-b", self.session, Journal(self.path),
                                     fixture("track-b.event.v1alpha1.schema.json"), transport=transport)
        restarted.emit("resource.changed", event)
        self.assertEqual(1, len(calls))
        self.assertEqual(self.session.project_id, calls[0][0]["X-Project-Id"])
        self.assertGreaterEqual(len(calls[0][0]["Idempotency-Key"]), 8)

    def test_retry_dlq_and_target_circuits_are_isolated(self):
        journal = Journal(self.path)
        failures = DurableDelivery(journal, "track-a", "v1", lambda *_: (_ for _ in ()).throw(OSError("down")),
                                   attempts=2, base_delay=0, sleeper=lambda _: None,
                                   breaker=CircuitBreaker(threshold=99))
        with self.assertRaises(DeliveryError): failures.send("key-a", "op", {"x": 1})
        self.assertEqual("dead-letter", journal.delivery("track-a", "key-a")["state"])
        healthy = DurableDelivery(journal, "track-b", "v1", lambda *_: {"ok": True}, attempts=1)
        self.assertEqual({"ok": True}, healthy.send("key-b", "op", {"x": 1}))
        self.assertEqual("delivered", journal.delivery("track-b", "key-b")["state"])

    def test_contract_and_project_mismatch_fail_closed(self):
        event = fixture("track-b-event-v1alpha1.json")
        client = TrackBHttpClient("http://track-b", self.session, Journal(self.path),
                                  fixture("track-b.event.v1alpha1.schema.json"),
                                  transport=lambda *_args, **_kwargs: self.fail("must not send"), attempts=1)
        with self.assertRaises(DeliveryError): client.emit("resource.changed", event)


if __name__ == "__main__": unittest.main()
