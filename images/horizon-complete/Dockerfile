ARG HORIZON_BASE=quay.io/airshipit/horizon:2026.1-ubuntu_noble@sha256:b40e1595290e6240cbba79cdd4243ac8f7b49dc8667f117ef6d3a5aac6aecb23
FROM ${HORIZON_BASE}

USER root

# Build the production dashboard from an upstream image in one pass.  No
# registry.dcn parent is allowed here: this is the bootstrap path for an empty
# Harbor.  Remote wheels are checksum-verified before extraction.
ADD https://tarballs.openstack.org/octavia-dashboard/octavia_dashboard-17.0.0-py3-none-any.whl /tmp/octavia_dashboard.whl
ADD https://tarballs.openstack.org/designate-dashboard/designate_dashboard-22.0.0-py3-none-any.whl /tmp/designate_dashboard.whl
ADD https://tarballs.openstack.org/magnum-ui/magnum_ui-18.0.0-py3-none-any.whl /tmp/magnum_ui.whl
ADD https://tarballs.openstack.org/python-magnumclient/python_magnumclient-4.10.0-py3-none-any.whl /tmp/python_magnumclient.whl
ADD https://tarballs.openstack.org/python-heatclient/python_heatclient-5.1.0-py3-none-any.whl /tmp/python_heatclient.whl
COPY openstack_vpc_dashboard.whl /tmp/openstack_vpc_dashboard.whl
COPY magnum-ui/enhance_magnum_ui.py /tmp/enhance_magnum_ui.py

RUN echo "c0698143689bc25576799eb9558a0452874171995406230b72c8b79f4af8d56f  /tmp/octavia_dashboard.whl" | sha256sum -c - \
    && echo "5937bb7c901f59142d97afc14dd7e48b9e80ea679e9c25d214d5eb88b632716c  /tmp/designate_dashboard.whl" | sha256sum -c - \
    && echo "93139ab8e6401a7069fa22b0f39deecc9defd73eed62f0441b0923926914f72a  /tmp/magnum_ui.whl" | sha256sum -c - \
    && echo "4d2717f0e98202dfc8ef8f966186dec39ef221e1e4e666a4dc08a17445acb039  /tmp/python_magnumclient.whl" | sha256sum -c - \
    && echo "7c9b29265cdc9256d60ed9974d38469b76a99976e1ca50263faad11e6942433d  /tmp/python_heatclient.whl" | sha256sum -c - \
    && python3 -m zipfile -e /tmp/octavia_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/designate_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/openstack_vpc_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/python_magnumclient.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/python_heatclient.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/magnum_ui.whl /var/lib/openstack/lib/python3.12/site-packages \
    && cp /var/lib/openstack/lib/python3.12/site-packages/octavia_dashboard/enabled/_*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/designatedashboard/enabled/_17*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/enabled/_31*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/enabled/_1395_compute_network_interfaces.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/enabled/_2360_admin_network_interfaces.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/enabled/_13*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/enabled/_23*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && sed -i 's/\$gray-lighter/#eeeeee/g' /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/static/dashboard/container-infra/clusters/clusters.scss \
    && rm -f /tmp/*.whl

ENV MAGNUM_UI_STATIC=/var/lib/openstack/lib/python3.12/site-packages/magnum_ui/static/dashboard/container-infra
COPY magnum-ui/overlay/clusters/panel.html ${MAGNUM_UI_STATIC}/clusters/panel.html
COPY magnum-ui/overlay/clusters/workflow/ ${MAGNUM_UI_STATIC}/clusters/workflow/
COPY magnum-ui/overlay/clusters/details/ ${MAGNUM_UI_STATIC}/clusters/details/
COPY magnum-ui/overlay/clusters/platform.scss ${MAGNUM_UI_STATIC}/clusters/_platform.scss
RUN python3 /tmp/enhance_magnum_ui.py \
    && sed -i '$a @import "platform";' ${MAGNUM_UI_STATIC}/clusters/clusters.scss \
    && rm -f /tmp/enhance_magnum_ui.py \
    && grep -q 'Create Kubernetes Cluster' ${MAGNUM_UI_STATIC}/clusters/create/create.service.js \
    && grep -q 'Argo CD' ${MAGNUM_UI_STATIC}/clusters/workflow/review.html \
    && grep -q 'Provisioning timeline' ${MAGNUM_UI_STATIC}/clusters/details/overview.html \
    && grep -q 'Rolling Kubernetes Upgrade' ${MAGNUM_UI_STATIC}/clusters/details/overview.html \
    && grep -q 'Download Kubeconfig' ${MAGNUM_UI_STATIC}/clusters/actions.module.js

# Local Octavia workflow patches and self-service Identity integration are
# copied from this repository; the VPC wheel is built from its separately
# locked Git repository by build-all-images.sh.
ENV LBAASV2_WORKFLOW=/var/lib/openstack/lib/python3.12/site-packages/octavia_dashboard/static/dashboard/project/lbaasv2/workflow
COPY octavia-workflow/model.service.js ${LBAASV2_WORKFLOW}/model.service.js
COPY octavia-workflow/loadbalancer.html ${LBAASV2_WORKFLOW}/loadbalancer/loadbalancer.html
COPY octavia-workflow/loadbalancer.controller.js ${LBAASV2_WORKFLOW}/loadbalancer/loadbalancer.controller.js
COPY octavia-workflow/listener.html ${LBAASV2_WORKFLOW}/listener/listener.html
COPY octavia-workflow/listener.controller.js ${LBAASV2_WORKFLOW}/listener/listener.controller.js
COPY octavia-workflow/pool.html ${LBAASV2_WORKFLOW}/pool/pool.html
COPY octavia-workflow/pool.controller.js ${LBAASV2_WORKFLOW}/pool/pool.controller.js
COPY project-selfservice/project_selfservice_dashboard/ /var/lib/openstack/lib/python3.12/site-packages/project_selfservice_dashboard/
COPY project-selfservice/identity_projects_patch/tables.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/tables.py
COPY project-selfservice/identity_projects_patch/urls.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/urls.py
COPY project-selfservice/identity_projects_patch/views.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/views.py
COPY project-selfservice/enabled/_1800_project_selfservice_app.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_1800_project_selfservice_app.py

RUN enabled=/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/enabled \
    && local_enabled=/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled \
    && sed -i "s/^PANEL_GROUP = 'network'$/PANEL_GROUP = 'vpc'/" "$local_enabled/_1482_project_load_balancer_panel.py" \
    && rm -f "$enabled/_1410_network_panel_group.py" "$enabled/_1420_project_network_topology_panel.py" \
       "$enabled/_1430_project_network_panel.py" "$enabled/_1440_project_routers_panel.py" \
       "$enabled/_1480_security_groups_panel.py" "$enabled/_1490_project_floating_ips_panel.py" \
       "$enabled/_1500_project_trunks_panel.py" "$enabled/_1510_project_network_qos_panel.py" \
       "$enabled/_1520_project_floating_ip_portforwardings_panel.py" \
    && python3 -c "import octavia_dashboard, designatedashboard, openstack_vpc_dashboard, project_selfservice_dashboard, magnum_ui, magnumclient, heatclient" \
    && python3 -m compileall -q /var/lib/openstack/lib/python3.12/site-packages/project_selfservice_dashboard \
    && test -f "$local_enabled/_1395_compute_network_interfaces.py" \
    && test -f "$local_enabled/_1482_project_load_balancer_panel.py" \
    && test -f "$local_enabled/_2360_admin_network_interfaces.py" \
    && test -f "$local_enabled/_1800_project_selfservice_app.py" \
    && grep -q "PANEL_GROUP = 'vpc'" "$local_enabled/_1482_project_load_balancer_panel.py" \
    && grep -q 'ADD_INSTALLED_APPS' "$local_enabled/_1800_project_selfservice_app.py"
