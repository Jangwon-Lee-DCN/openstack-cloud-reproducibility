from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import uuid4

from .store import Store


@dataclass(frozen=True)
class UsageSample:
    sample_id: str
    project_id: str
    period: str
    meter: str
    quantity: Decimal
    watermark: str


@dataclass(frozen=True)
class Rate:
    version: str
    meter: str
    unit_price: Decimal


class DeterministicTelemetrySource:
    def __init__(self, samples: list[UsageSample]):
        self.samples = sorted(samples, key=lambda sample: (sample.watermark, sample.sample_id))

    def after(self, project_id: str, watermark: str | None) -> list[UsageSample]:
        return [sample for sample in self.samples
                if sample.project_id == project_id and (watermark is None or sample.watermark > watermark)]


class LedgerRepository:
    def __init__(self, store: Store):
        self.store = store

    def aggregate(self, source_name: str, project_id: str, source: DeterministicTelemetrySource,
                  rates: dict[str, Rate]) -> dict:
        checkpoint = self.store.connection.execute(
            "SELECT watermark FROM telemetry_checkpoints WHERE source=? AND project_id=?",
            (source_name, project_id),
        ).fetchone()
        watermark = checkpoint[0] if checkpoint else None
        samples = source.after(project_id, watermark)
        inserted = 0
        with self.store.transaction() as db:
            for sample in samples:
                db.execute(
                    "INSERT OR IGNORE INTO usage_raw VALUES(?,?,?,?,?,?,?)",
                    (project_id, sample.sample_id, sample.period, sample.meter,
                     str(sample.quantity), sample.watermark, datetime.now(UTC).isoformat()),
                )
            raw_rows = db.execute(
                "SELECT sample_id,period,meter,quantity FROM usage_raw WHERE project_id=? ORDER BY watermark,sample_id",
                (project_id,),
            ).fetchall()
            for raw in raw_rows:
                rate = rates.get(raw[2])
                if not rate:
                    continue
                quantity = Decimal(raw[3])
                cost = (quantity * rate.unit_price).quantize(Decimal("0.000001"), ROUND_HALF_EVEN)
                cursor = db.execute(
                    "INSERT OR IGNORE INTO cost_ledger VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid4()), project_id, raw[0], raw[1], raw[2], str(quantity),
                     str(rate.unit_price), str(cost), rate.version, datetime.now(UTC).isoformat()),
                )
                inserted += cursor.rowcount
            if samples:
                new_watermark = max(sample.watermark for sample in samples)
                db.execute(
                    "INSERT INTO telemetry_checkpoints VALUES(?,?,?,?) "
                    "ON CONFLICT(source,project_id) DO UPDATE SET watermark=excluded.watermark,updated_at=excluded.updated_at",
                    (source_name, project_id, new_watermark, datetime.now(UTC).isoformat()),
                )
                watermark = new_watermark
        missing_rows = self.store.connection.execute(
            "SELECT DISTINCT r.meter FROM usage_raw r LEFT JOIN cost_ledger l "
            "ON l.project_id=r.project_id AND l.sample_id=r.sample_id "
            "WHERE r.project_id=? AND l.sample_id IS NULL ORDER BY r.meter", (project_id,)).fetchall()
        missing = [row[0] for row in missing_rows]
        return {"inserted": inserted, "watermark": watermark, "coverage": "incomplete" if missing else "complete",
                "missing_meters": missing}

    def entries(self, project_id: str) -> list[dict]:
        rows = self.store.connection.execute(
            "SELECT sample_id,period,meter,quantity,unit_price,cost,rate_version FROM cost_ledger "
            "WHERE project_id=? ORDER BY period,sample_id", (project_id,))
        return [dict(row) for row in rows]
