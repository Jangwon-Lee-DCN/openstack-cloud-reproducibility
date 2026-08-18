from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN


MONEY_QUANTUM = Decimal("0.000001")


class FinOpsError(ValueError):
    pass


def decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FinOpsError("invalid decimal value") from exc
    if not result.is_finite():
        raise FinOpsError("decimal must be finite")
    return result


@dataclass(frozen=True)
class Meter:
    name: str
    unit: str
    unit_price: Decimal


@dataclass(frozen=True)
class RateCard:
    version: str
    currency: str
    effective_at: datetime
    meters: dict[str, Meter]

    def __post_init__(self):
        if not self.version or not self.currency or self.effective_at.tzinfo is None:
            raise FinOpsError("rate card must be versioned, zoned and denominated")
        if any(meter.unit_price < 0 for meter in self.meters.values()):
            raise FinOpsError("unit price cannot be negative")

    def rate(self, meter: str, occurred_at: datetime) -> Meter | None:
        return self.meters.get(meter) if occurred_at >= self.effective_at else None


@dataclass(frozen=True)
class RatedUsage:
    sample_id: str
    project_id: str
    period: str
    meter: str
    unit: str
    quantity: Decimal
    cost: Decimal | None
    rate_version: str | None
    status: str


def rate_usage(*, source_id: str, project_id: str, period: str, meter: str,
               quantity, occurred_at: datetime, card: RateCard) -> RatedUsage:
    qty = decimal(quantity)
    if qty < 0:
        raise FinOpsError("usage quantity cannot be negative")
    definition = card.rate(meter, occurred_at)
    sample_id = hashlib.sha256(
        f"{source_id}\0{project_id}\0{period}\0{meter}".encode()).hexdigest()
    if definition is None:
        return RatedUsage(sample_id, project_id, period, meter, "unknown", qty,
                          None, None, "incomplete")
    cost = (qty * definition.unit_price).quantize(MONEY_QUANTUM, ROUND_HALF_EVEN)
    return RatedUsage(sample_id, project_id, period, meter, definition.unit, qty,
                      cost, card.version, "rated")


def parse_cloudkitty_frames(document: dict, *, expected_project_id: str) -> list[dict]:
    """Normalize CloudKitty v1/v2 frames without trusting tenant IDs."""
    frames = document.get("dataframes", document.get("results", []))
    if not isinstance(frames, list):
        raise FinOpsError("CloudKitty response has no dataframe list")
    result = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise FinOpsError("invalid CloudKitty dataframe")
        project_id = frame.get("project_id") or frame.get("tenant_id")
        if project_id and project_id != expected_project_id:
            raise FinOpsError("CloudKitty returned a cross-project dataframe")
        period = frame.get("period", {})
        begin = period.get("begin") if isinstance(period, dict) and period else frame.get("begin")
        end = period.get("end") if isinstance(period, dict) and period else frame.get("end")
        resources = frame.get("resources")
        if begin and end and isinstance(resources, list):
            for row in resources:
                if not isinstance(row, dict) or not row.get("service"):
                    raise FinOpsError("invalid CloudKitty v1 rated resource")
                description = row.get("desc", {})
                if not isinstance(description, dict):
                    raise FinOpsError("invalid CloudKitty v1 resource description")
                row_project = description.get("project_id") or frame.get("tenant_id")
                if row_project and row_project != expected_project_id:
                    raise FinOpsError("CloudKitty returned a cross-project datapoint")
                identity = hashlib.sha256(json.dumps(
                    description, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                result.append({
                    "source_id": f"{begin}/{end}/{row['service']}/{identity}",
                    "project_id": expected_project_id,
                    "period": f"{begin}/{end}",
                    "meter": row["service"],
                    "quantity": str(decimal(row.get("volume", 0))),
                    "cloudkitty_cost": str(decimal(row.get("rating", 0))),
                })
            continue
        usage = frame.get("usage", {})
        if not begin or not end or not isinstance(usage, dict):
            raise FinOpsError("CloudKitty dataframe is missing period or usage")
        for meter, rows in sorted(usage.items()):
            for row in rows if isinstance(rows, list) else []:
                volume = row.get("vol", {})
                rating = row.get("rating", {})
                row_project = row.get("groupby", {}).get("project_id")
                if row_project and row_project != expected_project_id:
                    raise FinOpsError("CloudKitty returned a cross-project datapoint")
                identity = hashlib.sha256(json.dumps({
                    "groupby": row.get("groupby", {}),
                    "metadata": row.get("metadata", {}),
                    "description": row.get("desc"),
                }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                result.append({
                    "source_id": f"{begin}/{end}/{meter}/{identity}",
                    "project_id": expected_project_id,
                    "period": f"{begin}/{end}",
                    "meter": meter,
                    "quantity": str(decimal(volume.get("qty", 0))),
                    "cloudkitty_cost": str(decimal(rating.get("price", 0))),
                })
    return result


def canonical_rate_card(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AwsPrice:
    sku: str
    unit: str
    unit_price: Decimal


@dataclass(frozen=True)
class AwsMeterMapping:
    meter: str
    sku: str
    conversion_factor: Decimal = Decimal("1")


@dataclass(frozen=True)
class AwsCalibration:
    sku: str
    multiplier: Decimal
    error_percent: Decimal
    sample_count: int


def aws_cost_forecast(*, quantities: dict[str, Decimal], prices: dict[str, AwsPrice],
                      mappings: dict[str, AwsMeterMapping],
                      calibrations: dict[str, AwsCalibration], elapsed_fraction,
                      currency: str, region: str, price_version: str,
                      as_of: str) -> dict:
    """Project a month-end AWS comparison without mutating the billing ledger."""
    fraction = decimal(elapsed_fraction)
    if fraction <= 0 or fraction > 1:
        raise FinOpsError("elapsed_fraction must be greater than zero and at most one")
    if not currency or not region or not price_version:
        raise FinOpsError("AWS price provenance is required")
    lines = []
    missing = []
    total = lower = upper = Decimal("0")
    calibrated_samples = 0
    for meter, quantity in sorted(quantities.items()):
        mapping = mappings.get(meter)
        price = prices.get(mapping.sku) if mapping else None
        if not mapping or not price:
            missing.append(meter)
            continue
        qty = decimal(quantity)
        if qty < 0 or mapping.conversion_factor <= 0 or price.unit_price < 0:
            raise FinOpsError("AWS quantities, conversions and prices must be non-negative")
        projected = qty / fraction * mapping.conversion_factor
        raw_cost = projected * price.unit_price
        calibration = calibrations.get(mapping.sku)
        multiplier = calibration.multiplier if calibration else Decimal("1")
        error = calibration.error_percent if calibration else Decimal("25")
        if multiplier <= 0 or error < 0 or error > 100:
            raise FinOpsError("invalid AWS calibration")
        calibrated_samples += calibration.sample_count if calibration else 0
        cost = (raw_cost * multiplier).quantize(MONEY_QUANTUM, ROUND_HALF_EVEN)
        low = (cost * (Decimal("1") - error / 100)).quantize(MONEY_QUANTUM, ROUND_HALF_EVEN)
        high = (cost * (Decimal("1") + error / 100)).quantize(MONEY_QUANTUM, ROUND_HALF_EVEN)
        total += cost
        lower += low
        upper += high
        lines.append({"meter": meter, "sku": mapping.sku, "unit": price.unit,
                      "month_to_date_quantity": str(qty),
                      "projected_quantity": str(projected.quantize(MONEY_QUANTUM, ROUND_HALF_EVEN)),
                      "unit_price": str(price.unit_price), "multiplier": str(multiplier),
                      "error_percent": str(error), "cost": str(cost),
                      "lower": str(low), "upper": str(high)})
    confidence = min(95, 35 + min(calibrated_samples, 30) * 2)
    if missing:
        confidence = max(0, confidence - min(30, 5 * len(missing)))
    return {"provider": "aws", "region": region, "currency": currency,
            "price_version": price_version, "as_of": as_of,
            "elapsed_fraction": str(fraction), "estimate": str(total),
            "lower": str(lower), "upper": str(upper),
            "confidence_percent": confidence,
            "coverage": "incomplete" if missing else "complete",
            "missing_meters": missing, "lines": lines}
