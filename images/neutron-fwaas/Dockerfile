FROM quay.io/airshipit/neutron:2026.1-ubuntu_noble

USER root

# FWaaS 24.0.0 is the OpenStack 2026.1 release. The base Neutron image
# already contains its constrained runtime dependencies, so install only the
# released wheel into the existing OpenStack virtual environment.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip ca-certificates \
    && python3 -m pip install --break-system-packages --no-cache-dir --no-deps \
       --target=/var/lib/openstack/lib/python3.12/site-packages \
       https://tarballs.openstack.org/neutron-fwaas/neutron_fwaas-24.0.0-py3-none-any.whl \
    && /var/lib/openstack/bin/python3 -c \
       "from neutron_fwaas.services.firewall.service_drivers.ovn.firewall_l3_driver import OVNFwaasDriver" \
    && apt-get purge -y python3-pip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

USER neutron
