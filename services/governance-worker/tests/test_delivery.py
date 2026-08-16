import unittest

from governance_worker.delivery import (
    ReplayCache, SmtpDevelopmentFixture, WebhookDevelopmentFixture,
    canonical_payload, verify_webhook,
)
from governance_worker.workflows import WorkflowError


class DeliveryTest(unittest.TestCase):
    def test_webhook_signature_timestamp_and_replay(self):
        fixture = WebhookDevelopmentFixture(
            b"development-only-key", {"hooks.example.test"}, lambda host: ["93.184.216.34"])
        record = fixture.send("consumer", "https://hooks.example.test/events", {"id": "event"},
                              timestamp=1_000, nonce="unique")
        cache = ReplayCache()
        verify_webhook(fixture.key, "consumer", record["timestamp"], record["nonce"],
                       canonical_payload(record["payload"]), record["signature"], cache, now=1_001)
        with self.assertRaises(WorkflowError):
            verify_webhook(fixture.key, "consumer", record["timestamp"], record["nonce"],
                           canonical_payload(record["payload"]), record["signature"], cache, now=1_002)
        with self.assertRaises(WorkflowError):
            verify_webhook(fixture.key, "other", 1_000, "new", b"{}", "bad", ReplayCache(), now=1_001)

    def test_dns_rebinding_and_private_destinations_are_denied(self):
        fixture = WebhookDevelopmentFixture(
            b"key", {"hooks.example.test"}, lambda host: ["10.0.0.1"])
        with self.assertRaises(WorkflowError):
            fixture.send("c", "https://hooks.example.test/x", {}, timestamp=1, nonce="n")

    def test_smtp_fixture_is_allowlisted_and_secret_free(self):
        smtp = SmtpDevelopmentFixture({"example.test"})
        smtp.send("user@example.test", "ready", "operation-ready", {"operation_id": "1"})
        with self.assertRaises(WorkflowError):
            smtp.send("user@external.test", "ready", "template", {})
        with self.assertRaises(WorkflowError):
            smtp.send("user@example.test", "bad\nBcc: x", "template", {})
        with self.assertRaises(WorkflowError):
            smtp.send("user@example.test", "ready", "template", {"nested": {"token": "no"}})
        with self.assertRaises(WorkflowError):
            WebhookDevelopmentFixture(
                b"key", {"hooks.example.test"}, lambda host: ["93.184.216.34"]
            ).send("c", "https://hooks.example.test/x", {"nested": {"secret": "no"}}, timestamp=1, nonce="n")


if __name__ == "__main__":
    unittest.main()
