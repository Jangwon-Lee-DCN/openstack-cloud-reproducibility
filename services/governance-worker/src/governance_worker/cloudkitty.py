from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

from governance_api.finops import parse_cloudkitty_frames
from governance_api.providers import OpenStackClient
from governance_api.telemetry import DeterministicTelemetrySource, LedgerRepository, Rate, UsageSample


SHOWBACK_RATES = {
    "governance.acceptance": Decimal("1.000000"),
    "instance": Decimal("1.000000"),
    "memory": Decimal("0.010000"),
    "volume.size": Decimal("0.001000"),
    "snapshot.size": Decimal("0.001000"),
    "ip.floating": Decimal("0.100000"),
    "network.services.lb": Decimal("0.500000"),
    "radosgw.objects.size": Decimal("0.000500"),
}


class CloudKittyCollector:
    def __init__(self, endpoint: str, token: str, *, version="dcn-showback-v1"):
        if not endpoint or not token:
            raise ValueError("CloudKitty endpoint and scoped token are required")
        self.client = OpenStackClient(endpoint, token, timeout=10)
        self.version = version

    def collect(self, store, project_id: str, begin: str, end: str) -> dict:
        query = urlencode({"begin": begin, "end": end,
                           "filters": f"project_id:{project_id}", "limit": 1000})
        _, document = self.client.request(f"/v2/dataframes?{query}")
        normalized = parse_cloudkitty_frames(document, expected_project_id=project_id)
        samples = []
        for item in normalized:
            sample_id = hashlib.sha256(
                f"cloudkitty\0{item['source_id']}\0{project_id}\0{item['meter']}".encode()).hexdigest()
            samples.append(UsageSample(sample_id, project_id, item["period"], item["meter"],
                                       Decimal(item["quantity"]), item["period"].split("/", 1)[1]))
        rates = {meter: Rate(self.version, meter, price) for meter, price in SHOWBACK_RATES.items()}
        return LedgerRepository(store).aggregate(
            "cloudkitty-v2", project_id, DeterministicTelemetrySource(samples), rates)
