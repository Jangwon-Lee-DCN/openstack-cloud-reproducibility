FROM quay.io/airshipit/horizon:2026.1-ubuntu_noble

USER root

# Add the Horizon plugin matching OpenStack 2026.1. The wheel exposes the
# enabled panel, policy file, Angular assets, and Octavia API integration.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip ca-certificates \
    && python3 -m pip install --break-system-packages --no-cache-dir --no-deps \
       --target=/var/lib/openstack/lib/python3.12/site-packages \
       https://tarballs.openstack.org/octavia-dashboard/octavia_dashboard-17.0.0-py3-none-any.whl \
    && python3 -c "import octavia_dashboard" \
    && cp /var/lib/openstack/lib/python3.12/site-packages/octavia_dashboard/enabled/_1482_project_load_balancer_panel.py \
       /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && apt-get purge -y python3-pip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
