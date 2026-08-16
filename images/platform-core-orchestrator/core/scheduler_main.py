import os
import time

from .adapters import DeterministicProviders, InstanceProvisioner
from .openstack import CinderAdapter, NeutronAdapter, NovaAdapter, OpenStackSession
from .reconciler import ASGResourceProvider, AutoScalingReconciler
from .store import store_from_env


def main():
    mode = os.environ.get("CORE_RUNTIME_MODE", "production")
    store = store_from_env(os.environ)
    if mode == "development":
        providers = DeterministicProviders()
        reconciler = AutoScalingReconciler(store, ASGResourceProvider(InstanceProvisioner(providers, providers, providers)))
    elif mode == "real-openstack":
        required = ["OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD", "OS_PROJECT_NAME",
                    "OS_NOVA_ENDPOINT", "OS_NEUTRON_ENDPOINT", "OS_CINDER_ENDPOINT"]
        missing = [name for name in required if not os.environ.get(name)]
        if missing: raise RuntimeError("real ASG provider configuration is incomplete: " + ",".join(missing))
        session = OpenStackSession(os.environ["OS_AUTH_URL"], os.environ["OS_USERNAME"], os.environ["OS_PASSWORD"],
                                   os.environ["OS_PROJECT_NAME"], os.environ.get("OS_USER_DOMAIN_NAME", "Default"),
                                   os.environ.get("OS_PROJECT_DOMAIN_NAME", "Default"),
                                   {"nova": os.environ["OS_NOVA_ENDPOINT"], "neutron": os.environ["OS_NEUTRON_ENDPOINT"],
                                    "cinder": os.environ["OS_CINDER_ENDPOINT"]})
        provisioner = InstanceProvisioner(NovaAdapter(session), NeutronAdapter(session), CinderAdapter(session))
        reconciler = AutoScalingReconciler(store, ASGResourceProvider(provisioner))
    else:
        raise RuntimeError("real scheduler adapters are not configured; refusing production scheduler startup")
    poll = float(os.environ.get("SCHEDULER_POLL_SECONDS", "5"))
    while True:
        reconciler.reconcile_all()
        time.sleep(poll)
if __name__ == "__main__": main()
