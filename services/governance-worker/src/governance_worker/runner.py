from __future__ import annotations

import os
import time

from governance_api.outbox import OutboxRepository
from governance_api.store import Store
from .real import initialize_real_integrations


class RealScheduler:
    def __init__(self, store: Store, event_bus, *, owner="governance-worker"):
        self.outbox = OutboxRepository(store)
        self.event_bus = event_bus
        self.owner = owner

    def run_once(self) -> dict:
        claimed = self.outbox.claim(self.owner, limit=100, lease_seconds=30)
        result = {"claimed": len(claimed), "delivered": 0, "retried": 0, "dead": 0}
        for item in claimed:
            try:
                self.event_bus.publish({"id": item.id, "project_id": item.project_id,
                                        "event_type": item.event_type, "payload": item.payload})
                self.outbox.complete(item.id, self.owner)
                result["delivered"] += 1
            except Exception as exc:
                state = self.outbox.fail(item.id, self.owner, type(exc).__name__)
                result["dead" if state == "dead" else "retried"] += 1
        return result


def main():
    if os.getenv("GOVERNANCE_MODE", "production") != "development":
        raise SystemExit("development boundary is required")
    if os.getenv("GOVERNANCE_PROVIDER_MODE", "disabled") != "real":
        raise SystemExit("real providers are required; refusing fake execution")
    event_bus = initialize_real_integrations()
    store = Store(os.getenv("GOVERNANCE_DB_PATH", "/var/lib/governance/governance.db"))
    scheduler = RealScheduler(store, event_bus)
    if os.getenv("GOVERNANCE_RUN_ONCE") == "1":
        scheduler.run_once()
        return
    interval = max(1, int(os.getenv("GOVERNANCE_POLL_SECONDS", "5")))
    while True:
        scheduler.run_once()
        time.sleep(interval)


if __name__ == "__main__":
    main()
