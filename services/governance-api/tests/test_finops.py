import unittest
from datetime import UTC, datetime
from decimal import Decimal

from governance_api.finops import (
    FinOpsError, Meter, RateCard, canonical_rate_card, parse_cloudkitty_frames, rate_usage,
)
from governance_api.security import RequestContext
from governance_api.service import GovernanceService
from governance_api.store import Store
from governance_api.telemetry import DeterministicTelemetrySource, LedgerRepository, Rate, UsageSample


class FinOpsTests(unittest.TestCase):
    def setUp(self):
        self.card = RateCard(
            "dcn-showback-v1", "DCN-CREDIT", datetime(2026, 8, 1, tzinfo=UTC),
            {"instance": Meter("instance", "instance-hour", Decimal("1.125000"))})

    def test_decimal_rating_is_deterministic(self):
        rated = rate_usage(source_id="metric-1", project_id="p", period="2026-08",
                           meter="instance", quantity="2.5",
                           occurred_at=datetime(2026, 8, 2, tzinfo=UTC), card=self.card)
        replay = rate_usage(source_id="metric-1", project_id="p", period="2026-08",
                            meter="instance", quantity="2.5",
                            occurred_at=datetime(2026, 8, 2, tzinfo=UTC), card=self.card)
        self.assertEqual(rated, replay)
        self.assertEqual(rated.cost, Decimal("2.812500"))
        self.assertEqual(rated.status, "rated")

    def test_undefined_meter_remains_incomplete_for_later_rating(self):
        missing = rate_usage(source_id="metric-2", project_id="p", period="2026-08",
                             meter="new.meter", quantity="3",
                             occurred_at=datetime(2026, 8, 2, tzinfo=UTC), card=self.card)
        self.assertEqual(missing.status, "incomplete")
        self.assertIsNone(missing.cost)
        later = RateCard("v2", "DCN-CREDIT", datetime(2026, 8, 1, tzinfo=UTC),
                         {"new.meter": Meter("new.meter", "unit-hour", Decimal("2"))})
        completed = rate_usage(source_id="metric-2", project_id="p", period="2026-08",
                               meter="new.meter", quantity="3",
                               occurred_at=datetime(2026, 8, 2, tzinfo=UTC), card=later)
        self.assertEqual(completed.sample_id, missing.sample_id)
        self.assertEqual(completed.cost, Decimal("6.000000"))

    def test_cloudkitty_scope_and_shape(self):
        document = {"dataframes": [{"project_id": "p", "period": {"begin": "a", "end": "b"},
                    "usage": {"instance": [{"vol": {"qty": "2"}, "rating": {"price": "2.25"},
                                              "groupby": {"project_id": "p"}}]}}]}
        self.assertEqual(parse_cloudkitty_frames(document, expected_project_id="p")[0]["cloudkitty_cost"], "2.25")
        document["dataframes"][0]["project_id"] = "other"
        with self.assertRaises(FinOpsError):
            parse_cloudkitty_frames(document, expected_project_id="p")

    def test_cloudkitty_v1_scope_and_shape(self):
        document = {"dataframes": [{
            "begin": "2026-08-01T00:00:00", "end": "2026-08-01T01:00:00",
            "tenant_id": "p", "resources": [{"service": "instance", "volume": "2",
                "rating": "2.25", "desc": {"project_id": "p", "id": "vm-1"}}]}]}
        item = parse_cloudkitty_frames(document, expected_project_id="p")[0]
        self.assertEqual((item["meter"], item["quantity"], item["cloudkitty_cost"]),
                         ("instance", "2", "2.25"))
        document["dataframes"][0]["tenant_id"] = "other"
        with self.assertRaises(FinOpsError):
            parse_cloudkitty_frames(document, expected_project_id="p")

    def test_cloudkitty_resource_identity_is_stable_across_frame_reordering(self):
        resources = [
            {"service": "instance", "volume": "2", "rating": "2",
             "desc": {"project_id": "p", "id": "vm-1"}},
            {"service": "instance", "volume": "3", "rating": "3",
             "desc": {"project_id": "p", "id": "vm-2"}},
        ]
        def parse(rows):
            return parse_cloudkitty_frames({"dataframes": [{
                "begin": "a", "end": "b", "tenant_id": "p", "resources": rows
            }]}, expected_project_id="p")
        original = {item["source_id"] for item in parse(resources)}
        reordered = {item["source_id"] for item in parse(list(reversed(resources)))}
        self.assertEqual(original, reordered)

    def test_rate_card_digest_is_canonical(self):
        self.assertEqual(canonical_rate_card({"b": 2, "a": 1}),
                         canonical_rate_card({"a": 1, "b": 2}))

    def test_usage_summary_is_project_scoped_and_exposes_coverage(self):
        store = Store()
        LedgerRepository(store).aggregate("cloudkitty-v2", "p", DeterministicTelemetrySource([
            UsageSample("one", "p", "2026-08", "instance", Decimal("1"), "001"),
            UsageSample("missing", "p", "2026-08", "future.meter", Decimal("1"), "002"),
        ]), {"instance": Rate("v1", "instance", Decimal("1"))})
        result = GovernanceService(store).page_usage_ledger(RequestContext("d", "p", "u"))
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["coverage"], "incomplete")
        self.assertEqual(result["missing_meters"], ["future.meter"])
        self.assertEqual(result["billing"], False)


if __name__ == "__main__":
    unittest.main()
