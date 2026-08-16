"""Read-only readiness probe for every Track A OpenStack provider dependency."""
import os

from .openstack import OpenStackSession


def build_session():
    names = {
        "nova": "OS_NOVA_ENDPOINT", "neutron": "OS_NEUTRON_ENDPOINT", "cinder": "OS_CINDER_ENDPOINT",
        "placement": "OS_PLACEMENT_ENDPOINT", "octavia": "OS_OCTAVIA_ENDPOINT", "aodh": "OS_AODH_ENDPOINT"}
    missing = [name for name in ("OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD", "OS_PROJECT_NAME", *names.values())
               if not os.environ.get(name)]
    if missing: raise RuntimeError("provider probe configuration is incomplete: " + ",".join(missing))
    return OpenStackSession(os.environ["OS_AUTH_URL"], os.environ["OS_USERNAME"], os.environ["OS_PASSWORD"],
                            os.environ["OS_PROJECT_NAME"], os.environ.get("OS_USER_DOMAIN_NAME", "Default"),
                            os.environ.get("OS_PROJECT_DOMAIN_NAME", "Default"),
                            {service: os.environ[variable] for service, variable in names.items()})


def main():
    session = build_session()
    session.authenticate()
    probes = {"nova": "/servers/detail?limit=1", "neutron": "/v2.0/networks?limit=1",
              "cinder": f"/v3/{session.project_id}/volumes/detail?limit=1",
              # Placement inventory is service-admin scoped on this cloud. The
              # project principal verifies the version endpoint only; mutation
              # stays explicitly unsupported/DEGRADED.
              "placement": "/", "octavia": "/v2/lbaas/loadbalancers?limit=1",
              "aodh": "/v2/alarms?limit=1"}
    for service, path in probes.items(): session.probe(service, path)
    print("OPENSTACK_PROVIDER_READ_ONLY_PROBE_OK")


if __name__ == "__main__": main()
