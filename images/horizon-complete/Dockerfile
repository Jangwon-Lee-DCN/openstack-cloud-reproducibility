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
ADD https://tarballs.openstack.org/manila-ui/manila_ui-15.0.0-py3-none-any.whl /tmp/manila_ui.whl
ADD https://tarballs.openstack.org/python-manilaclient/python_manilaclient-6.0.0-py3-none-any.whl /tmp/python_manilaclient.whl
ADD https://tarballs.openstack.org/masakari-dashboard/masakari_dashboard-14.0.0-py3-none-any.whl /tmp/masakari_dashboard.whl
COPY openstack_vpc_dashboard.whl /tmp/openstack_vpc_dashboard.whl
COPY openstack_telemetry_dashboard.whl /tmp/openstack_telemetry_dashboard.whl
COPY openstack_s3_dashboard.whl /tmp/openstack_s3_dashboard.whl
COPY magnum-ui/enhance_magnum_ui.py /tmp/enhance_magnum_ui.py
COPY enhance_images_ui.py /tmp/enhance_images_ui.py
COPY patch_federated_logout.py /tmp/patch_federated_logout.py
COPY image_catalog/index_split.html /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/templates/project/images/index_split.html
COPY platform_navigation.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/platform_navigation.py
COPY enabled/_9999_platform_navigation.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_9999_platform_navigation.py
COPY settings/0001_production_region.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/local_settings.d/0001_production_region.py
COPY region_selector.html /var/lib/openstack/lib/python3.12/site-packages/horizon/templates/horizon/common/_region_selector.html
COPY service_catalog/ /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/service_catalog/
COPY enabled/_1380_dcn_service_catalog.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_1380_dcn_service_catalog.py
COPY tenant-service-catalog.yaml /etc/openstack-dashboard/dcn-service-catalog.yaml
COPY track-b/governance_dashboard/ /var/lib/openstack/lib/python3.12/site-packages/governance_dashboard/
COPY track-b/governance_dashboard/enabled/_3100_governance.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_3100_governance.py
COPY track-b/governance_dashboard/enabled/_3110_governance_overview.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_3110_governance_overview.py
COPY track-b/governance_dashboard/enabled/_3120_governance_cost_management.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_3120_governance_cost_management.py
COPY track-b/governance_dashboard/enabled/_3121_governance_cost_overview.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_3121_governance_cost_overview.py
COPY track-b/governance_dashboard/enabled/_3122_governance_cost_budgets.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_3122_governance_cost_budgets.py
COPY track-b/governance_dashboard/enabled/_3123_governance_aws_forecast.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_3123_governance_aws_forecast.py
COPY track-b/governance_dashboard/enabled/_3124_governance_cost_profiles.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_3124_governance_cost_profiles.py

RUN echo "c0698143689bc25576799eb9558a0452874171995406230b72c8b79f4af8d56f  /tmp/octavia_dashboard.whl" | sha256sum -c - \
    && echo "5937bb7c901f59142d97afc14dd7e48b9e80ea679e9c25d214d5eb88b632716c  /tmp/designate_dashboard.whl" | sha256sum -c - \
    && echo "93139ab8e6401a7069fa22b0f39deecc9defd73eed62f0441b0923926914f72a  /tmp/magnum_ui.whl" | sha256sum -c - \
    && echo "4d2717f0e98202dfc8ef8f966186dec39ef221e1e4e666a4dc08a17445acb039  /tmp/python_magnumclient.whl" | sha256sum -c - \
    && echo "7c9b29265cdc9256d60ed9974d38469b76a99976e1ca50263faad11e6942433d  /tmp/python_heatclient.whl" | sha256sum -c - \
    && echo "4e064674a7d49648a70c56fda84a63201d2c472bd30bbc048955c17111b19995  /tmp/manila_ui.whl" | sha256sum -c - \
    && echo "079a248ed632c30a3c625d31b04b0899fdc4ff3944a06cede5ca62e2a4f8ecd6  /tmp/python_manilaclient.whl" | sha256sum -c - \
    && echo "73fe9c0f48af35f25baae83a98e77e98ab6b419d45d64277331bc1d75e1cdd53  /tmp/masakari_dashboard.whl" | sha256sum -c - \
    && python3 -m zipfile -e /tmp/octavia_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/designate_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/openstack_vpc_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/python_magnumclient.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/python_heatclient.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/magnum_ui.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/python_manilaclient.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/manila_ui.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/masakari_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/openstack_telemetry_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && python3 -m zipfile -e /tmp/openstack_s3_dashboard.whl /var/lib/openstack/lib/python3.12/site-packages \
    && cp /var/lib/openstack/lib/python3.12/site-packages/octavia_dashboard/enabled/_*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/designatedashboard/enabled/_17*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/enabled/_31*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/enabled/_1395_compute_network_interfaces.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/enabled/_2360_admin_network_interfaces.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/enabled/_13*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/magnum_ui/enabled/_23*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/manila_ui/local/enabled/_*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/masakaridashboard/local/enabled/_*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/cloud_telemetry_dashboard/enabled/_*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
    && cp /var/lib/openstack/lib/python3.12/site-packages/cloud_s3_dashboard/enabled/_*.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/ \
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

RUN python3 /tmp/enhance_images_ui.py \
    && rm -f /tmp/enhance_images_ui.py \
    && grep -q "Platform Images" /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/project/images/images/tables.py \
    && grep -q "dcn_image_class" /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/project/images/images/tables.py \
    && grep -q "template_name = 'project/images/index_split.html'" /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/project/images/views.py \
    && grep -q "window.WEBROOT" /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/templates/project/images/index_split.html \
    && grep -q "image-linked-resources" /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/templates/project/images/index_split.html \
    && grep -q "image-inspector-retry" /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/templates/project/images/index_split.html \
    && ! grep -q "CAPI Kubernetes" /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/project/images/images/tables.py

RUN python3 /tmp/patch_federated_logout.py \
    && rm -f /tmp/patch_federated_logout.py \
    && grep -q 'Flush the local session before starting RP-initiated logout' /var/lib/openstack/lib/python3.12/site-packages/openstack_auth/views.py \
    && python3 -m py_compile /var/lib/openstack/lib/python3.12/site-packages/openstack_auth/views.py

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
COPY project-selfservice/identity_projects_patch/tabs.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/tabs.py
COPY project-selfservice/identity_projects_patch/templates/projects/index.html /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/templates/projects/index.html
COPY project-selfservice/identity_projects_patch/templates/projects/detail.html /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/templates/identity/projects/detail.html
COPY project-selfservice/identity_projects_patch/templates/projects/overview.html /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/templates/identity/projects/overview.html
COPY project-selfservice/enabled/_1800_project_selfservice_app.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_1800_project_selfservice_app.py
COPY project-selfservice/enabled/_2850_admin_project_operations.py /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled/_2850_admin_project_operations.py

RUN enabled=/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/enabled \
    && local_enabled=/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/enabled \
    && sed -i "s/^PANEL_GROUP = 'network'$/PANEL_GROUP = 'vpc'/" "$local_enabled/_1482_project_load_balancer_panel.py" \
    && rm -f "$enabled/_1420_project_network_topology_panel.py" \
       "$enabled/_1480_security_groups_panel.py" "$enabled/_1490_project_floating_ips_panel.py" \
       "$enabled/_1500_project_trunks_panel.py" "$enabled/_1510_project_network_qos_panel.py" \
       "$enabled/_1520_project_floating_ip_portforwardings_panel.py" \
    && sed -i "s/region_name = request.COOKIES.get('services_region')/region_name = getattr(request.user, 'services_region', None) or request.COOKIES.get('services_region')/" /var/lib/openstack/lib/python3.12/site-packages/masakaridashboard/api/api.py \
    && sed -i "/region_name = getattr(request.user, 'services_region'/a\\    if region_name in ('RegionOne', 'RegionOne-VM'):\\n        region_name = None" /var/lib/openstack/lib/python3.12/site-packages/masakaridashboard/api/api.py \
    && grep -q "getattr(request.user, 'services_region'" /var/lib/openstack/lib/python3.12/site-packages/masakaridashboard/api/api.py \
    && python3 -c "import octavia_dashboard, designatedashboard, openstack_vpc_dashboard, project_selfservice_dashboard, magnum_ui, magnumclient, heatclient, manila_ui, manilaclient, masakaridashboard, cloud_telemetry_dashboard, cloud_s3_dashboard, governance_dashboard" \
    && grep -q 'remove_stock_actions(tables.InstancesTable, {"associate", "disassociate"})' /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/customization.py \
    && test ! -e /var/lib/openstack/lib/python3.12/site-packages/openstack_vpc_dashboard/api/native_inventory.py \
    && python3 -m compileall -q /var/lib/openstack/lib/python3.12/site-packages/project_selfservice_dashboard \
    && test -f "$local_enabled/_1395_compute_network_interfaces.py" \
    && test -f "$local_enabled/_1380_dcn_service_catalog.py" \
    && test -f "$local_enabled/_1482_project_load_balancer_panel.py" \
    && test -f "$local_enabled/_2360_admin_network_interfaces.py" \
    && test -f "$local_enabled/_1800_project_selfservice_app.py" \
    && test -f "$local_enabled/_9010_manila_project_add_shares_panel_to_share_panel_group.py" \
    && test -f "$local_enabled/_50_masakaridashboard.py" \
    && test -f "$local_enabled/_1610_project_metrics.py" \
    && test -f "$local_enabled/_1620_project_alarms.py" \
    && test -f "$local_enabled/_2610_admin_telemetry_health.py" \
    && test -f "$local_enabled/_1930_project_s3.py" \
    && test ! -e "$local_enabled/_2030_resilience.py" \
    && test ! -e "$local_enabled/_2040_resilience_operations.py" \
    && test ! -e "$local_enabled/_2210_core_orchestration.py" \
    && test ! -e /var/lib/openstack/lib/python3.12/site-packages/dcn_resilience_dashboard \
    && test ! -e /var/lib/openstack/lib/python3.12/site-packages/dcn_core_orchestration \
    && test -f "$local_enabled/_3100_governance.py" \
    && test -f "$local_enabled/_3110_governance_overview.py" \
    && test -f "$local_enabled/_3120_governance_cost_management.py" \
    && test -f "$local_enabled/_3121_governance_cost_overview.py" \
    && test -f "$local_enabled/_3122_governance_cost_budgets.py" \
    && test -f "$local_enabled/_3123_governance_aws_forecast.py" \
    && test -f "$local_enabled/_3124_governance_cost_profiles.py" \
    && test -f "$local_enabled/_9999_platform_navigation.py" \
    && test -f /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/local_settings.d/0001_production_region.py \
    && grep -q 'GOVERNANCE_FAKE_API_ENDPOINT' /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/local_settings.d/0001_production_region.py \
    && test -f /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/dashboards/identity/projects/tabs.py \
    && grep -q "PANEL_GROUP = 'vpc'" "$local_enabled/_1482_project_load_balancer_panel.py" \
    && grep -q 'ADD_INSTALLED_APPS.*cloud_telemetry_dashboard' "$local_enabled/_1600_project_observability.py" \
    && grep -q 'ADD_INSTALLED_APPS.*cloud_s3_dashboard' "$local_enabled/_1930_project_s3.py" \
    && grep -q 'ADD_INSTALLED_APPS.*openstack_dashboard.service_catalog' "$local_enabled/_1380_dcn_service_catalog.py" \
    && grep -q 'baremetal-virtual' /etc/openstack-dashboard/dcn-service-catalog.yaml \
    && grep -q 'openstack_dashboard.platform_navigation' "$local_enabled/_9999_platform_navigation.py" \
    && grep -q 'ADD_INSTALLED_APPS' "$local_enabled/_1800_project_selfservice_app.py" \
    && chmod -R a+rX /var/lib/openstack/lib/python3.12/site-packages
