from __future__ import annotations

import os
import time

from governance_api.outbox import OutboxRepository
from governance_api.store import Store
from .loops import DeterministicProviders, FakeReconciliationLoops


class FakeScheduler:
    def __init__(self, store: Store, *, owner="fake-worker", fail_event_types=()):
        self.outbox = OutboxRepository(store)
        self.owner = owner
        self.fail_event_types = set(fail_event_types)

    def run_once(self) -> dict:
        claimed = self.outbox.claim(self.owner, limit=100, lease_seconds=30)
        result = {"claimed": len(claimed), "delivered": 0, "retried": 0, "dead": 0}
        for item in claimed:
            if item.event_type in self.fail_event_types:
                state = self.outbox.fail(item.id, self.owner, "fake_provider_failure")
                result["dead" if state == "dead" else "retried"] += 1
            else:
                self.outbox.complete(item.id, self.owner)
                result["delivered"] += 1
        return result


def main():
    if os.getenv("GOVERNANCE_MODE", "production") != "development":
        raise SystemExit("real providers are not implemented; refusing production mode")
    if os.getenv("GOVERNANCE_PROVIDER_MODE", "disabled") != "fake":
        raise SystemExit("only explicit fake provider mode is available")
    store = Store(os.getenv("GOVERNANCE_DB_PATH", "/var/lib/governance/governance.db"))
    scheduler = FakeScheduler(store, fail_event_types=filter(None, os.getenv("GOVERNANCE_FAKE_FAILURES", "").split(",")))
    loops = FakeReconciliationLoops(DeterministicProviders())
    if os.getenv("GOVERNANCE_RUN_ONCE") == "1":
        scheduler.run_once()
        return
    interval = max(1, int(os.getenv("GOVERNANCE_POLL_SECONDS", "5")))
    while True:
        scheduler.run_once()
        time.sleep(interval)


if __name__ == "__main__":
    main()
