from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.request import Request, urlopen


class LokiAuditExporter:
    SOURCE = "governance-audit-loki"

    def __init__(self, url: str, *, timeout: int = 10):
        self.url = url.rstrip("/") + "/loki/api/v1/push"
        self.timeout = timeout

    def export(self, store, limit: int = 100) -> int:
        checkpoint = store.connection.execute(
            "SELECT watermark FROM telemetry_checkpoints WHERE source=? AND project_id='*'",
            (self.SOURCE,),).fetchone()
        after = int(checkpoint[0]) if checkpoint else 0
        rows = list(store.connection.execute(
            "SELECT seq,body FROM audit_events WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)))
        if not rows:
            return 0
        streams = []
        for row in rows:
            event = store.decode(row[1])
            occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
            if occurred.tzinfo is None:
                occurred = occurred.replace(tzinfo=UTC)
            streams.append({"stream": {
                "service": "governance-audit", "openstack_project_id": event["project_id"],
                "audit_action": event["action"], "audit_outcome": event["outcome"],
            }, "values": [[str(int(occurred.timestamp() * 1_000_000_000)),
                            json.dumps(event, sort_keys=True, separators=(",", ":"))]]})
        request = Request(self.url, data=json.dumps({"streams": streams}).encode(), method="POST",
                          headers={"Content-Type": "application/json", "X-Scope-OrgID": "openstack"})
        with urlopen(request, timeout=self.timeout) as response:
            if response.status not in (200, 204):
                raise RuntimeError(f"Loki push returned HTTP {response.status}")
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with store.transaction() as db:
            db.execute(
                "INSERT INTO telemetry_checkpoints(source,project_id,watermark,updated_at) VALUES(?, '*', ?, ?) "
                "ON CONFLICT(source,project_id) DO UPDATE SET watermark=excluded.watermark,updated_at=excluded.updated_at",
                (self.SOURCE, str(rows[-1][0]), now))
        return len(rows)
