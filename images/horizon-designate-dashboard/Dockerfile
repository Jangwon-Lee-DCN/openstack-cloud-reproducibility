ARG HORIZON_BASE=registry.dcn.ssu.ac.kr/openstack/horizon@sha256:cf1b6e3d6e83f5aef38691f2cc9198e0ded029ac81b7eade2fc12ba4df92a668
FROM ${HORIZON_BASE}

USER root

# Preserve the already-deployed Octavia and VPC panels from the immutable
# base image, then add the OpenStack 2026.1 Designate Dashboard release.
ADD https://tarballs.openstack.org/designate-dashboard/designate_dashboard-22.0.0-py3-none-any.whl /tmp/designate_dashboard.whl
RUN echo "5937bb7c901f59142d97afc14dd7e48b9e80ea679e9c25d214d5eb88b632716c  /tmp/designate_dashboard.whl" \
      | sha256sum -c - \
    && python3 -m zipfile -e \
      /tmp/designate_dashboard.whl \
      /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -c "import designatedashboard" \
    && cp /var/lib/openstack/lib/python3.12/site-packages/designatedashboard/enabled/_17*.py \
      /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && rm /tmp/designate_dashboard.whl
