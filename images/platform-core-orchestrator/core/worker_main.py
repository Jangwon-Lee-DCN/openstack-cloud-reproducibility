import os
import time
import uuid

from .adapters import DeterministicProviders, InstanceProvisioner
from .openstack import CinderAdapter, NeutronAdapter, NovaAdapter, OpenStackSession
from .store import Store
from .worker import DurableWorker


def main():
    mode = os.environ.get("CORE_RUNTIME_MODE", "production")
    if mode == "development":
        providers = DeterministicProviders()
        provisioner = InstanceProvisioner(providers, providers, providers)
    elif mode == "real-openstack":
        required = ["OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD", "OS_PROJECT_NAME",
                    "OS_NOVA_ENDPOINT", "OS_NEUTRON_ENDPOINT", "OS_CINDER_ENDPOINT"]
        missing = [name for name in required if not os.environ.get(name)]
        if missing: raise RuntimeError("real provider configuration is incomplete: " + ",".join(missing))
        session = OpenStackSession(os.environ["OS_AUTH_URL"], os.environ["OS_USERNAME"], os.environ["OS_PASSWORD"],
                                   os.environ["OS_PROJECT_NAME"], os.environ.get("OS_USER_DOMAIN_NAME", "Default"),
                                   os.environ.get("OS_PROJECT_DOMAIN_NAME", "Default"),
                                   {"nova": os.environ["OS_NOVA_ENDPOINT"], "neutron": os.environ["OS_NEUTRON_ENDPOINT"],
                                    "cinder": os.environ["OS_CINDER_ENDPOINT"]})
        provisioner = InstanceProvisioner(NovaAdapter(session), NeutronAdapter(session), CinderAdapter(session))
    else:
        raise RuntimeError("real provider adapters are not configured; refusing production worker startup")
    worker = DurableWorker(Store(os.environ.get("CORE_DB_PATH", "/data/core.db")), os.environ.get("WORKER_ID", str(uuid.uuid4())))
    poll = float(os.environ.get("WORKER_POLL_SECONDS", "1"))
    while True:
        if worker.execute_once(provisioner) is None:
            time.sleep(poll)


if __name__ == "__main__": main()
