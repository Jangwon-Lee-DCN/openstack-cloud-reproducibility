import os
import time

from .adapters import DeterministicProviders
from .reconciler import AutoScalingReconciler
from .store import Store


def main():
    if os.environ.get("CORE_RUNTIME_MODE", "production") != "development":
        raise RuntimeError("real scheduler adapters are not configured; refusing production scheduler startup")
    reconciler = AutoScalingReconciler(Store(os.environ.get("CORE_DB_PATH", "/data/core.db")), DeterministicProviders())
    poll = float(os.environ.get("SCHEDULER_POLL_SECONDS", "5"))
    while True:
        reconciler.reconcile_all()
        time.sleep(poll)


if __name__ == "__main__": main()
