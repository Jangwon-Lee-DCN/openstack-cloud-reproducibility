import os
import time

from .adapters import DeterministicProviders
from .reconciler import AutoScalingReconciler
from .store import store_from_env


def main():
    mode = os.environ.get("CORE_RUNTIME_MODE", "production")
    store = store_from_env(os.environ)
    if mode == "development":
        reconciler = AutoScalingReconciler(store, DeterministicProviders())
    elif mode == "real-openstack":
        reconciler = DegradedRealScheduler(store)
    else:
        raise RuntimeError("real scheduler adapters are not configured; refusing production scheduler startup")
    poll = float(os.environ.get("SCHEDULER_POLL_SECONDS", "5"))
    while True:
        reconciler.reconcile_all()
        time.sleep(poll)


class DegradedRealScheduler:
    """Fail-safe ASG boundary until member resource-set persistence lands.

    Zero-capacity groups are safely reconciled. Any non-zero request becomes
    DEGRADED rather than silently using deterministic/fake compute.
    """
    def __init__(self, store): self.store = store
    def reconcile_all(self):
        with self.store.tx() as db:
            rows = list(db.execute("SELECT id,desired FROM auto_scaling_groups WHERE state IN ('SCALING','DEGRADED')"))
            results = []
            for row in rows:
                state = "ACTIVE" if row["desired"] == 0 else "DEGRADED"
                db.execute("UPDATE auto_scaling_groups SET state=? WHERE id=?", (state, row["id"]))
                results.append({"group_id": str(row["id"]), "desired": row["desired"], "actual": 0, "state": state})
            return results


if __name__ == "__main__": main()
