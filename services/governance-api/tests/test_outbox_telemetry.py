import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from governance_api.operation import FakeOperationClient
from governance_api.outbox import OutboxRepository
from governance_api.security import RequestContext
from governance_api.service import GovernanceService
from governance_api.store import Store
from governance_api.telemetry import DeterministicTelemetrySource, LedgerRepository, Rate, UsageSample


class MutableClock:
    def __init__(self):
        self.value = datetime.now(UTC) + timedelta(seconds=1)

    def __call__(self):
        return self.value


class OutboxTelemetryTest(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.ctx = RequestContext("d", "p", "u")

    def test_resource_and_outbox_are_atomic_and_deduplicated(self):
        service = GovernanceService(self.store, FakeOperationClient())
        body = {"event_type": "operation.succeeded"}
        service.ingest_notification(self.ctx, body, key="idempotent", request_id="req")
        service.ingest_notification(self.ctx, body, key="idempotent", request_id="req")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM resources").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM outbox").fetchone()[0], 1)

    def test_lease_expiry_retry_and_dlq(self):
        GovernanceService(self.store).ingest_notification(
            self.ctx, {"event_type": "operation.failed"}, key="delivery", request_id="req")
        clock = MutableClock()
        outbox = OutboxRepository(self.store, clock=clock)
        item = outbox.claim("worker-a", lease_seconds=10)[0]
        self.assertEqual(outbox.claim("worker-b"), [])
        clock.value += timedelta(seconds=11)
        recovered = outbox.claim("worker-b")[0]
        for attempt in range(5):
            state = outbox.fail(recovered.id, "worker-b", "smtp_unavailable", max_attempts=5)
            if state == "dead":
                break
            clock.value += timedelta(seconds=2 ** (attempt + 1))
            recovered = outbox.claim("worker-b")[0]
        self.assertEqual(outbox.status(item.id), "dead")

    def test_immutable_decimal_ledger_and_checkpoint(self):
        source = DeterministicTelemetrySource([
            UsageSample("s1", "p", "2026-08", "cpu", Decimal("1.25"), "001"),
            UsageSample("s2", "p", "2026-08", "unknown", Decimal("2"), "002"),
        ])
        ledger = LedgerRepository(self.store)
        rate = {"cpu": Rate("rate-v1", "cpu", Decimal("0.1234567"))}
        first = ledger.aggregate("fake-gnocchi", "p", source, rate)
        second = ledger.aggregate("fake-gnocchi", "p", source, rate)
        self.assertEqual(first["coverage"], "incomplete")
        self.assertEqual(first["missing_meters"], ["unknown"])
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(ledger.entries("p")[0]["cost"], "0.154321")
        completed = ledger.aggregate(
            "fake-gnocchi", "p", source,
            {**rate, "unknown": Rate("rate-v1", "unknown", Decimal("2.0"))},
        )
        self.assertEqual(completed["coverage"], "complete")
        self.assertEqual(len(ledger.entries("p")), 2)


if __name__ == "__main__":
    unittest.main()
