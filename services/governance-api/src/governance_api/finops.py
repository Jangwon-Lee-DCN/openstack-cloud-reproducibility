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
    """Normalize CloudKitty v2 frames without trusting tenant IDs from callers."""
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
        begin = period.get("begin") if isinstance(period, dict) else frame.get("begin")
        end = period.get("end") if isinstance(period, dict) else frame.get("end")
        usage = frame.get("usage", {})
        if not begin or not end or not isinstance(usage, dict):
            raise FinOpsError("CloudKitty dataframe is missing period or usage")
        for meter, rows in sorted(usage.items()):
            for index, row in enumerate(rows if isinstance(rows, list) else []):
                volume = row.get("vol", {})
                rating = row.get("rating", {})
                row_project = row.get("groupby", {}).get("project_id")
                if row_project and row_project != expected_project_id:
                    raise FinOpsError("CloudKitty returned a cross-project datapoint")
                result.append({
                    "source_id": f"{begin}/{end}/{meter}/{index}",
                    "project_id": expected_project_id,
                    "period": f"{begin}/{end}",
                    "meter": meter,
                    "quantity": str(decimal(volume.get("qty", 0))),
                    "cloudkitty_cost": str(decimal(rating.get("price", 0))),
                })
    return result


def canonical_rate_card(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
