FROM quay.io/airshipit/octavia:2026.1-ubuntu_noble

USER root

# The upstream Airship Octavia image does not include the OVN provider.
# Install the 2026.1 provider and its constrained runtime dependencies into
# the existing OpenStack venv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip ca-certificates \
    && python3 -m pip install --break-system-packages --no-cache-dir \
       --constraint=https://releases.openstack.org/constraints/upper/2026.1 \
       --target=/var/lib/openstack/lib/python3.12/site-packages \
       https://tarballs.openstack.org/ovn-octavia-provider/ovn_octavia_provider-10.0.0-py3-none-any.whl \
    && /var/lib/openstack/bin/python3 -c "import ovn_octavia_provider" \
    && apt-get purge -y python3-pip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
