# Base is the already-published octavia-dashboard image (octavia_dashboard
# 17.0.0 installed + panel enabled) that the vpc-dashboard and
# designate-dashboard images are themselves layered on top of in production.
# Building from raw upstream Horizon instead of this digest silently drops
# those other plugins when this image is deployed directly -- do not change
# this default without updating the downstream vpc-dashboard/designate-dashboard
# build args to match.
ARG HORIZON_BASE=registry.dcn.ssu.ac.kr/openstack/horizon@sha256:fb146bd85456861201fa3a2f1c610779b7300c9b245b72eca01fe41ee5a7bbf5
FROM ${HORIZON_BASE}

USER root

# vpc-control-plane extension: let this native LBaaS v2 wizard show the
# Octavia provider ("L4 only" / "L4 + L7") as an explicit, first-class
# choice, and filter the listener protocol / pool algorithm lists to match
# whichever provider is selected -- rather than only discovering an
# unsupported combination (e.g. HTTP on "ovn") as a raw Octavia 501 after
# the whole wizard has already been submitted. Files replace the
# upstream octavia-dashboard 17.0.0 originals 1:1 at the same paths.
ENV LBAASV2_WORKFLOW=/var/lib/openstack/lib/python3.12/site-packages/octavia_dashboard/static/dashboard/project/lbaasv2/workflow
COPY model.service.js ${LBAASV2_WORKFLOW}/model.service.js
COPY loadbalancer.html ${LBAASV2_WORKFLOW}/loadbalancer/loadbalancer.html
COPY loadbalancer.controller.js ${LBAASV2_WORKFLOW}/loadbalancer/loadbalancer.controller.js
COPY listener.html ${LBAASV2_WORKFLOW}/listener/listener.html
COPY listener.controller.js ${LBAASV2_WORKFLOW}/listener/listener.controller.js
COPY pool.html ${LBAASV2_WORKFLOW}/pool/pool.html
COPY pool.controller.js ${LBAASV2_WORKFLOW}/pool/pool.controller.js

# Move the one native octavia-dashboard panel registration into Horizon's VPC
# group. Do not add a second enabled file for the same panel class: Horizon's
# Dashboard.get_panel_groups() removes registered classes while iterating its
# groups and raises KeyError when one class is present in two groups.
RUN panel_file=/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_1482_project_load_balancer_panel.py \
    && test "$(grep -c "^PANEL_GROUP = 'network'$" "${panel_file}")" = 1 \
    && sed -i "s/^PANEL_GROUP = 'network'$/PANEL_GROUP = 'vpc'/" "${panel_file}" \
    && test "$(grep -c "^PANEL_GROUP = 'vpc'$" "${panel_file}")" = 1
