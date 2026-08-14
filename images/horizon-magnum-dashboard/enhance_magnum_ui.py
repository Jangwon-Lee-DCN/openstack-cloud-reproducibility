#!/usr/bin/env python3
"""Apply the DCN CAPI/GitOps UX contract to the pinned upstream Magnum UI."""

import os
from pathlib import Path


ROOT = Path(os.environ.get(
    "MAGNUM_UI_ROOT",
    "/var/lib/openstack/lib/python3.12/site-packages/magnum_ui/static/dashboard/container-infra",
))


def replace(path: str, old: str, new: str, count: int = 1) -> None:
    target = ROOT / path
    value = target.read_text()
    actual = value.count(old)
    if actual != count:
        raise SystemExit(f"{target}: expected {count} occurrence(s), found {actual}: {old!r}")
    target.write_text(value.replace(old, new))


# The platform supports and recommends the Octavia-backed API endpoint. Keep
# the request contract upstream-compatible while choosing useful PoC defaults.
workflow = "clusters/workflow/workflow.service.js"
replace(
    workflow,
    """      var availabilityZoneTitleMap = [{value: '',
        name: gettext('Choose an Availability Zone')}];
""",
    "",
)
replace(
    workflow,
    """                    {
                      key: 'availability_zone',
                      type: 'select',
                      title: gettext('Availability Zone'),
                      titleMap: availabilityZoneTitleMap,
                      required: true
                    },
""",
    "",
)
replace(
    workflow,
    """          master_count: null,
          master_flavor_id: '',
          node_count: null,
          flavor_id: '',""",
    """          master_count: 1,
          master_flavor_id: '',
          node_count: 1,
          flavor_id: '',""",
)
replace(workflow, "master_lb_enabled: false,", "master_lb_enabled: true,")
replace(workflow, "master_lb_floating_ip_enabled: false,", "master_lb_floating_ip_enabled: true,")
replace(workflow, "gettext('Create New Network')", "gettext('Create an isolated cluster network')")
replace(workflow, "gettext('Kubernetes API Loadbalancer')", "gettext('Kubernetes API endpoint')")
replace(workflow, "gettext('Enable Load Balancer for Kubernetes API')", "gettext('Use the supported Octavia load balancer')")
replace(workflow, "gettext('Auto-scale Worker Nodes')", "gettext('Enable worker autoscaling')")
replace(workflow, "gettext('Automatically Repair Unhealthy Nodes')", "gettext('Enable CAPI machine health remediation')")
replace(workflow, "gettext('Additional Labels')", "gettext('Advanced Magnum/CAPI labels')")
replace(workflow, "gettext('I do want to override Template and Workflow Labels')", "gettext('Allow overriding profile-managed labels')")

# Add a final, read-only review step. It reads the same model submitted by the
# upstream service, so the view cannot drift from the API request fields.
needle = """            {
              title: gettext('Advanced'),"""
review = """            {
              title: gettext('Review'),
              type: 'section',
              htmlClass: 'row',
              items: [
                {
                  type: 'section',
                  htmlClass: 'col-md-12',
                  items: [
                    {
                      type: 'template',
                      templateUrl: basePath + 'clusters/workflow/review.html'
                    }
                  ]
                }
              ]
            },
            {
              title: gettext('Advanced'),"""
replace(workflow, needle, review)

create = "clusters/create/create.service.js"
replace(create, "spinnerModal.showModalSpinner(gettext('Loading'));", "// Dependencies load inside the modal; avoid a global template-cache spinner.")
replace(create, "workflow.init(gettext('Create New Cluster'), $scope)", "workflow.init(gettext('Create Kubernetes Cluster'), $scope)")
replace(create, "create_timeout: 60,", "create_timeout: 60,")

# Operations are asynchronous GitOps changes. Do not offer a second mutation
# while Magnum reports another reconciliation in progress or a failed state.
for operation in (
    "clusters/resize/resize.service.js",
    "clusters/rolling-upgrade/upgrade.service.js",
):
    replace(
        operation,
        """    function allowed() {
      return $qExtensions.booleanAsPromise(true);
    }""",
        """    function allowed(selected) {
      var status = selected && selected.status ? selected.status : '';
      return $qExtensions.booleanAsPromise(
        /^(CREATE|UPDATE|RESUME)_COMPLETE$/.test(status));
    }""",
    )

config = "clusters/config/config.service.js"
replace(config, "selected.name + \"_config\"", "selected.name + \"_kubeconfig.yaml\"")

actions = "clusters/actions.module.js"
replace(actions, "gettext('Get Cluster Config')", "gettext('Download Kubeconfig')")
replace(actions, "gettext('Resize Cluster')", "gettext('Scale Worker Node Group')")
replace(actions, "gettext('Rolling Cluster Upgrade')", "gettext('Rolling Kubernetes Upgrade')")

# Remove legacy Heat vocabulary from the resource list and expose operational
# fields that Magnum actually returns for the CAPI driver.
module = "clusters/clusters.module.js"
for old, new in (
    ("Status", "Provisioning State"),
    ("Health Status", "Workload Health"),
    ("Control Plane Count", "Control Planes"),
    ("Node Count", "Workers"),
):
    replace(module, f"label: gettext('{old}')", f"label: gettext('{new}')")
    replace(module, f"'label': gettext('{old}')", f"'label': gettext('{new}')")

print("Magnum UI CAPI/GitOps enhancements applied")
