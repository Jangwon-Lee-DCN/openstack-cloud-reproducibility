import unittest
from datetime import UTC, datetime
from decimal import Decimal

from governance_api.finops import (
    AwsCalibration, AwsMeterMapping, AwsPrice, FinOpsError, Meter, RateCard,
    aws_cost_forecast, canonical_rate_card, parse_cloudkitty_frames, rate_usage,
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

    def test_aws_forecast_calibrates_and_exposes_range(self):
        result = aws_cost_forecast(
            quantities={"instance": Decimal("100"), "unmapped": Decimal("1")},
            prices={"ec2.test": AwsPrice("ec2.test", "instance-hour", Decimal("2"))},
            mappings={"instance": AwsMeterMapping("instance", "ec2.test", Decimal("1"))},
            calibrations={"ec2.test": AwsCalibration(
                "ec2.test", Decimal("1.10"), Decimal("10"), 8)},
            elapsed_fraction="0.5", currency="USD", region="ap-northeast-2",
            price_version="aws-2026-08-17", as_of="2026-08-17T00:00:00Z")
        self.assertEqual(result["estimate"], "440.000000")
        self.assertEqual((result["lower"], result["upper"]),
                         ("396.000000", "484.000000"))
        self.assertEqual(result["missing_meters"], ["unmapped"])
        self.assertEqual(result["confidence_percent"], 46)

    def test_aws_forecast_rejects_invalid_fraction(self):
        with self.assertRaises(FinOpsError):
            aws_cost_forecast(quantities={}, prices={}, mappings={}, calibrations={},
                              elapsed_fraction="0", currency="USD",
                              region="ap-northeast-2", price_version="v1", as_of="now")

    def test_aws_forecast_uses_project_ledger_and_budget(self):
        store = Store()
        service = GovernanceService(store)
        ctx = RequestContext("d", "p", "u")
        LedgerRepository(store).aggregate("cloudkitty-v2", "p", DeterministicTelemetrySource([
            UsageSample("one", "p", "2026-08", "instance", Decimal("100"), "001"),
            UsageSample("other", "other", "2026-08", "instance", Decimal("999"), "001"),
        ]), {"instance": Rate("v1", "instance", Decimal("1"))})
        profile = service.create_aws_price_profile(ctx, {
            "version": "aws-v1", "region": "ap-northeast-2", "currency": "USD",
            "effective_at": "2026-08-01T00:00:00Z",
            "prices": [{"sku": "ec2.test", "unit": "instance-hour", "unit_price": "2"}],
            "mappings": [{"meter": "instance", "sku": "ec2.test"}],
        }, key="price-profile", request_id="req-price")
        calibration = service.create_aws_calibration_profile(ctx, {
            "version": "cur-v1", "calibrations": [{"sku": "ec2.test",
                "multiplier": "1.1", "error_percent": "10", "sample_count": 8}],
        }, key="calibration-profile", request_id="req-cal")
        budget = service.create_budget(ctx, {"amount": "500"}, key="budget-profile",
                                       request_id="req-budget")
        result = service.aws_forecast(ctx, period="2026-08", price_profile_id=profile["id"],
                                      calibration_profile_id=calibration["id"],
                                      elapsed_fraction="0.5", budget_id=budget["id"])
        self.assertEqual(result["estimate"], "440.000000")
        self.assertEqual(result["budget"]["forecast_percent"], "88.00")
        self.assertFalse(result["budget"]["exceeded"])


if __name__ == "__main__":
    unittest.main()
