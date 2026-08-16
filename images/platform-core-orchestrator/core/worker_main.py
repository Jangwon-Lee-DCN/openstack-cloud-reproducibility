import os
import time
import uuid

from .adapters import DeterministicProviders, InstanceProvisioner
from .store import Store
from .worker import DurableWorker


def main():
    mode = os.environ.get("CORE_RUNTIME_MODE", "production")
    if mode != "development":
        raise RuntimeError("real provider adapters are not configured; refusing production worker startup")
    providers = DeterministicProviders()
    provisioner = InstanceProvisioner(providers, providers, providers)
    worker = DurableWorker(Store(os.environ.get("CORE_DB_PATH", "/data/core.db")), os.environ.get("WORKER_ID", str(uuid.uuid4())))
    poll = float(os.environ.get("WORKER_POLL_SECONDS", "1"))
    while True:
        if worker.execute_once(provisioner) is None:
            time.sleep(poll)


if __name__ == "__main__": main()
