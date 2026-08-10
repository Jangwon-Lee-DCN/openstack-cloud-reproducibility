FROM quay.io/airshipit/neutron:2026.1-ubuntu_noble@sha256:6ddd490d615ea57b72be83607067b255d4c4339431e8950b6c70c59db0a6ddae

USER root

# FWaaS 24.0.0 is the OpenStack 2026.1 release. The base Neutron image
# already contains its constrained runtime dependencies, so install only the
# released wheel into the existing OpenStack virtual environment.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip ca-certificates curl \
    && curl -fsSL -o /tmp/neutron_fwaas-24.0.0-py3-none-any.whl \
       https://tarballs.openstack.org/neutron-fwaas/neutron_fwaas-24.0.0-py3-none-any.whl \
    && echo "1dd53ea72b532f117dbc67b8a47e1a40dce6b8f1f7e07dbe520a2a0548935927  /tmp/neutron_fwaas-24.0.0-py3-none-any.whl" | sha256sum -c - \
    && python3 -m pip install --break-system-packages --no-cache-dir --no-deps \
       --target=/var/lib/openstack/lib/python3.12/site-packages \
       /tmp/neutron_fwaas-24.0.0-py3-none-any.whl \
    && /var/lib/openstack/bin/python3 -c \
       "from neutron_fwaas.services.firewall.service_drivers.ovn.firewall_l3_driver import OVNFwaasDriver" \
    && apt-get purge -y python3-pip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/neutron_fwaas-24.0.0-py3-none-any.whl

USER neutron
