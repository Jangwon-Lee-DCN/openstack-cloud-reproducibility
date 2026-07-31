#!/usr/bin/env bash
set -euo pipefail

# Read-only: the caller supplies existing kubectl and project-scoped OpenStack access.
project_namespace="${1:?usage: audit-vpc-neutron-drift.sh PROJECT_NAMESPACE [REPORT.json]}"
report_path="${2:-vpc-neutron-drift-${project_namespace}.json}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

kubectl -n "${project_namespace}" get securitygroups.vpc.dcn.ssu.ac.kr,elasticips.vpc.dcn.ssu.ac.kr,natgateways.vpc.dcn.ssu.ac.kr -o json >"${tmp_dir}/crs.json"
openstack security group list -f json >"${tmp_dir}/sg.json"
openstack floating ip list -f json >"${tmp_dir}/fip.json"
openstack router list -f json >"${tmp_dir}/router.json"

jq -n --slurpfile cr "${tmp_dir}/crs.json" --slurpfile sg "${tmp_dir}/sg.json" --slurpfile fip "${tmp_dir}/fip.json" --slurpfile router "${tmp_dir}/router.json" '
  def ids($kind; $field): [$cr[0].items[] | select(.kind == $kind) | .status[$field] // empty];
  def actual_ids($rows): [$rows[0][] | .ID // .Id // .id];
  (ids("SecurityGroup"; "securityGroupID")) as $desired_sg |
  (ids("ElasticIP"; "floatingIPID")) as $desired_fip |
  (ids("NatGateway"; "routerID")) as $desired_router |
  (actual_ids($sg)) as $actual_sg | (actual_ids($fip)) as $actual_fip | (actual_ids($router)) as $actual_router |
  {
    generatedAt: (now | todateiso8601), mode: "read-only",
    missingActual: {
      securityGroups: ($desired_sg - $actual_sg),
      floatingIPs: ($desired_fip - $actual_fip),
      routers: ($desired_router - $actual_router)
    },
    untrackedManaged: {
      securityGroups: [$sg[0][] | select(((.Description // .description // "") | contains("vpc-control-plane"))) | (.ID // .Id // .id)] - $desired_sg,
      floatingIPs: [$fip[0][] | select(((.Description // .description // "") | contains("vpc-control-plane"))) | (.ID // .Id // .id)] - $desired_fip,
      routers: [$router[0][] | select(((.Description // .description // "") | contains("vpc-control-plane"))) | (.ID // .Id // .id)] - $desired_router
    }
  } |
  .summary = {missingActual: ([.missingActual[] | length] | add), untrackedManaged: ([.untrackedManaged[] | length] | add)}
' >"${report_path}"
cat "${report_path}"

if [[ -n "${PUSHGATEWAY_URL:-}" ]]; then
  missing="$(jq '.summary.missingActual' "${report_path}")"
  untracked="$(jq '.summary.untrackedManaged' "${report_path}")"
  curl --fail --silent --show-error --data-binary @- "${PUSHGATEWAY_URL%/}/metrics/job/vpc-neutron-drift/project_namespace/${project_namespace}" <<EOF
# HELP vpc_neutron_drift_resources Resources whose CRM and Neutron state differ.
# TYPE vpc_neutron_drift_resources gauge
vpc_neutron_drift_resources{project_namespace="${project_namespace}",type="missing_actual"} ${missing}
vpc_neutron_drift_resources{project_namespace="${project_namespace}",type="untracked_managed"} ${untracked}
EOF
fi
