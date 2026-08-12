#!/usr/bin/env bash
set -euo pipefail

# Read-only readiness inventory. Exit 0 means acceptance can start; exit 1
# identifies prerequisites without creating or changing cluster resources.
project_namespace=${VPC_ACCEPTANCE_PROJECT_NAMESPACE:-}
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
infra_repo=${DCN_INFRA_REPO:-$(CDPATH= cd -- "$repo_root/../.." && pwd)}
failures=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
exists() { kubectl "$@" >/dev/null 2>&1; }

context=$(kubectl config current-context 2>/dev/null || true)
[[ -n "$context" ]] && pass "kubectl context: $context" || fail "kubectl has no current context"

if [[ -f "$infra_repo/inventory/site.yaml" ]] && python3 - "$infra_repo/inventory/site.yaml" <<'PY'
import json, subprocess, sys, yaml
site = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))["site"]
expected = {node["hostname"]: rack["name"] for rack in site["racks"] for node in rack["nodes"]}
live = json.loads(subprocess.check_output(["kubectl", "get", "nodes", "-o", "json"], text=True))["items"]
errors = []
for node in live:
    name = node["metadata"]["name"]
    actual = node["metadata"].get("labels", {}).get("topology.kubernetes.io/zone")
    if name not in expected:
        errors.append(f"{name}: absent from inventory/site.yaml")
    elif actual != expected[name]:
        errors.append(f"{name}: zone={actual!r}, expected={expected[name]!r}")
if errors:
    raise SystemExit("; ".join(errors))
PY
then
  pass "live node Rack labels match inventory/site.yaml"
else
  fail "live node Rack labels do not match the authoritative site inventory"
fi

for crd in connectivityprobes.vpc.dcn.ssu.ac.kr vpcendpoints.vpc.dcn.ssu.ac.kr flowlogconfigs.vpc.dcn.ssu.ac.kr privatednszones.vpc.dcn.ssu.ac.kr; do
  exists get crd "$crd" && pass "CRD $crd" || fail "CRD $crd is not installed"
done

if exists -n openstack get job rack-external-networks && \
   [[ $(kubectl -n openstack get job rack-external-networks -o jsonpath='{.status.succeeded}') == 1 ]]; then
  rack_script=$(kubectl -n openstack get configmap rack-external-networks -o jsonpath='{.data.reconcile\.sh}' 2>/dev/null || true)
  config_contract=$(kubectl -n openstack get configmap rack-external-networks -o jsonpath='{.metadata.labels.dcn\.ssu\.ac\.kr/rack-address-contract}' 2>/dev/null || true)
  job_contract=$(kubectl -n openstack get job rack-external-networks -o jsonpath='{.metadata.labels.dcn\.ssu\.ac\.kr/rack-address-contract}' 2>/dev/null || true)
  pool_contract=true
  for required in 'address_scope=' 'subnet_pool=' public-rack-1-gateway public-rack-1-fip public-rack-1-lb public-rack-2-gateway public-rack-2-fip public-rack-2-lb public-rack-3-gateway public-rack-3-fip public-rack-3-lb; do
    [[ "$rack_script" == *"$required"* ]] || pool_contract=false
  done
  [[ "$config_contract" == purpose-pools-v2 && "$job_contract" == purpose-pools-v2 ]] || pool_contract=false
  if [[ "$pool_contract" == true ]]; then
    pass "deployed Rack Address Scope and gateway/FIP/LB pool contract"
  else
    fail "deployed Phase 54 still uses legacy single-subnet Rack pools"
  fi
else
  fail "Rack external-network reconciliation Job is absent or incomplete"
fi

for deployment in vpc-control-plane-controller-manager vpc-facade; do
  if exists -n vpc-control-plane-system get deployment "$deployment"; then
    desired=$(kubectl -n vpc-control-plane-system get deployment "$deployment" -o jsonpath='{.spec.replicas}')
    ready=$(kubectl -n vpc-control-plane-system get deployment "$deployment" -o jsonpath='{.status.readyReplicas}')
    image=$(kubectl -n vpc-control-plane-system get deployment "$deployment" -o jsonpath='{.spec.template.spec.containers[0].image}')
    [[ "$desired" -gt 0 && "$ready" == "$desired" ]] && pass "$deployment ready=$ready/$desired" || fail "$deployment ready=${ready:-0}/$desired"
    [[ "$image" == *@sha256:* ]] && pass "$deployment digest pinned" || fail "$deployment image is not digest pinned"
  else
    fail "$deployment is not installed"
  fi
done

# P0-1 includes Magnum workload clusters, not only VPC facade resources. The
# accepted image must use one Rack label for both the resolved public network
# and every CAPO control-plane/worker failure domain.
if exists -n openstack get statefulset magnum-conductor; then
  magnum_desired=$(kubectl -n openstack get statefulset magnum-conductor -o jsonpath='{.spec.replicas}')
  magnum_ready=$(kubectl -n openstack get statefulset magnum-conductor -o jsonpath='{.status.readyReplicas}')
  magnum_image=$(kubectl -n openstack get statefulset magnum-conductor -o jsonpath='{.spec.template.spec.containers[0].image}')
  [[ "$magnum_desired" -gt 0 && "$magnum_ready" == "$magnum_desired" ]] && \
    pass "magnum-conductor ready=$magnum_ready/$magnum_desired" || \
    fail "magnum-conductor ready=${magnum_ready:-0}/$magnum_desired"
  [[ "$magnum_image" == *@sha256:* ]] && pass "magnum-conductor digest pinned" || fail "magnum-conductor image is not digest pinned"
  if kubectl -n openstack exec statefulset/magnum-conductor -c magnum-conductor -- \
    python3 -c 'import inspect; from oslo_config import cfg; from magnum_capi_gitops import driver; mapping=dict(cfg.CONF.capi_gitops.rack_external_networks); assert mapping == {"rack-1":"public-rack-1","rack-2":"public-rack-2","rack-3":"public-rack-3"}; canonical=inspect.getsource(driver.Driver._canonical_request); placement=inspect.getsource(driver.Driver._rack_placement); assert "availability_zone" in canonical and "external_network_id" in canonical and "availability_zone" in placement' \
    >/dev/null 2>&1; then
    pass "live Magnum driver Rack placement contract"
  else
    fail "live Magnum driver does not bind Rack AZ to its external-network request"
  fi
else
  fail "magnum-conductor is not installed"
fi

if exists -n magnum-gitops-system get deployment magnum-capi-repository-writer; then
  writer_desired=$(kubectl -n magnum-gitops-system get deployment magnum-capi-repository-writer -o jsonpath='{.spec.replicas}')
  writer_ready=$(kubectl -n magnum-gitops-system get deployment magnum-capi-repository-writer -o jsonpath='{.status.readyReplicas}')
  writer_image=$(kubectl -n magnum-gitops-system get deployment magnum-capi-repository-writer -o jsonpath='{.spec.template.spec.containers[0].image}')
  [[ "$writer_desired" -gt 0 && "$writer_ready" == "$writer_desired" ]] && \
    pass "Magnum repository writer ready=$writer_ready/$writer_desired" || \
    fail "Magnum repository writer ready=${writer_ready:-0}/$writer_desired"
  [[ "$writer_image" == *@sha256:* ]] && pass "Magnum repository writer digest pinned" || fail "Magnum repository writer image is not digest pinned"
  if kubectl -n magnum-gitops-system exec deployment/magnum-capi-repository-writer -- \
    python3 -c 'import sys; sys.path.insert(0,"/app/magnum-driver"); import prototype; request={"cluster_uuid":"11111111-1111-4111-8111-111111111111","name":"preflight","kubernetes_version":"v1.34.4","machine_image_id":"image","availability_zone":"rack-2","external_network_id":"network","node_cidr":"10.0.0.0/24","dns_nameservers":["192.0.2.53"],"cloud_credentials_secret_name":"cloud","control_plane":{"count":1,"flavor":"m1"},"node_groups":[{"name":"workers","count":1,"flavor":"m1"}]}; values=prototype.chart_values(request); assert values["controlPlane"]["omitFailureDomain"] is False; assert values["controlPlane"]["failureDomains"] == ["rack-2"]; assert values["nodeGroupDefaults"]["failureDomain"] == "rack-2"; assert all(group["failureDomain"] == "rack-2" for group in values["nodeGroups"])' \
    >/dev/null 2>&1; then
    pass "live Magnum renderer pins CAPO failure domains"
  else
    fail "live Magnum renderer does not pin CAPO machines to the selected Rack AZ"
  fi
else
  fail "Magnum repository writer is not installed"
fi

expected_endpoint_cidrs=${VPC_ENDPOINT_SERVICE_CIDRS:-192.168.21.0/24}
manager_args=$(kubectl -n vpc-control-plane-system get deployment vpc-control-plane-controller-manager -o jsonpath='{.spec.template.spec.containers[0].args}' 2>/dev/null || true)
facade_args=$(kubectl -n vpc-control-plane-system get deployment vpc-facade -o jsonpath='{.spec.template.spec.containers[0].args}' 2>/dev/null || true)
if [[ "$manager_args" == *"--vpc-endpoint-service-cidrs=${expected_endpoint_cidrs}"* && \
      "$facade_args" == *"--vpc-endpoint-service-cidrs=${expected_endpoint_cidrs}"* && \
      "$facade_args" == *"--availability-zones=rack-1,rack-2,rack-3"* ]]; then
  pass "live controller/facade Rack and Endpoint allowlist contract"
else
  fail "live controller/facade has not rolled out the Rack and Endpoint allowlist contract"
fi

if exists -n openstack get daemonset vpc-endpoint-agent; then
  endpoint_desired=$(kubectl -n openstack get daemonset vpc-endpoint-agent -o jsonpath='{.status.desiredNumberScheduled}')
  endpoint_ready=$(kubectl -n openstack get daemonset vpc-endpoint-agent -o jsonpath='{.status.numberReady}')
  endpoint_image=$(kubectl -n openstack get daemonset vpc-endpoint-agent -o jsonpath='{.spec.template.spec.containers[0].image}')
  [[ "$endpoint_desired" -gt 0 && "$endpoint_ready" == "$endpoint_desired" ]] && \
    pass "endpoint agent ready=$endpoint_ready/$endpoint_desired" || \
    fail "endpoint agent ready=${endpoint_ready:-0}/${endpoint_desired:-0}"
  [[ "$endpoint_image" == *@sha256:* ]] && pass "endpoint agent digest pinned" || fail "endpoint agent image is not digest pinned"
else
  fail "endpoint agent DaemonSet is not installed"
fi

for secret_ref in openstack/vpc-endpoint-policy-hmac vpc-control-plane-system/vpc-endpoint-policy-hmac; do
  secret_namespace=${secret_ref%/*}
  secret_name=${secret_ref#*/}
  encoded=$(kubectl -n "$secret_namespace" get secret "$secret_name" -o jsonpath='{.data.hmac-secret}' 2>/dev/null || true)
  if [[ -n "$encoded" ]] && [[ $(printf '%s' "$encoded" | base64 -d 2>/dev/null | wc -c) -ge 32 ]]; then
    pass "$secret_ref has a >=32-byte HMAC key"
  else
    fail "$secret_ref is missing or its hmac-secret is shorter than 32 bytes"
  fi
done

if exists -n openstack get deployment vpc-metadata-attestor; then
  attestor_desired=$(kubectl -n openstack get deployment vpc-metadata-attestor -o jsonpath='{.spec.replicas}')
  attestor_ready=$(kubectl -n openstack get deployment vpc-metadata-attestor -o jsonpath='{.status.readyReplicas}')
  attestor_image=$(kubectl -n openstack get deployment vpc-metadata-attestor -o jsonpath='{.spec.template.spec.containers[0].image}')
  [[ "$attestor_desired" -gt 0 && "$attestor_ready" == "$attestor_desired" ]] && \
    pass "metadata attestor ready=$attestor_ready/$attestor_desired" || \
    fail "metadata attestor ready=${attestor_ready:-0}/${attestor_desired:-0}"
  [[ "$attestor_image" == *@sha256:* ]] && pass "metadata attestor digest pinned" || fail "metadata attestor image is not digest pinned"
  if [[ "$attestor_desired" -gt 0 && "$attestor_ready" == "$attestor_desired" && "$attestor_image" == *@sha256:* ]] && \
     "$repo_root/deploy/scripts/verify-vpc-instance-identity.sh" >/dev/null 2>&1; then
    pass "trusted instance identity path"
  else
    fail "trusted instance identity path is installed but verification failed"
  fi
else
  fail "vpc-metadata-attestor is not installed"
fi

if [[ -z "$project_namespace" ]]; then
  fail "set VPC_ACCEPTANCE_PROJECT_NAMESPACE=vpc-<project-id>"
elif ! [[ "$project_namespace" =~ ^vpc-[a-z0-9]([a-z0-9-]{0,57}[a-z0-9])?$ ]]; then
  fail "invalid acceptance project namespace: $project_namespace"
elif ! exists get namespace "$project_namespace"; then
  fail "project namespace $project_namespace does not exist"
else
  exists -n "$project_namespace" get secret openstack-credentials && pass "$project_namespace project credential" || fail "$project_namespace/openstack-credentials is missing"
  exists -n "$project_namespace" get cronjob vpc-neutron-drift-auditor && pass "$project_namespace drift CronJob" || fail "$project_namespace drift CronJob is not installed"
fi

bgp_vars="$infra_repo/automation/inventory/production/group_vars/all.yml"
bgp_inventory="$infra_repo/automation/inventory/production/hosts.yml"
if [[ -f "$bgp_vars" && -f "$bgp_inventory" ]] && python3 - "$bgp_vars" "$bgp_inventory" 2>/dev/null <<'PY'
import ipaddress, sys, yaml
values = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
inventory = yaml.safe_load(open(sys.argv[2], encoding="utf-8"))
assert values.get("ovn_bgp_enabled") is True
assert values.get("confirm_ovn_bgp_policy_approved") is True
assert 64512 <= int(values.get("ovn_bgp_local_as", 0)) <= 65534
racks = values.get("ovn_bgp_racks", {})
assert set(racks) == {"rack-1", "rack-2", "rack-3"}
for rack, contract in racks.items():
    ipaddress.IPv4Address(contract["peer_ip"])
    assert 1 <= int(contract["peer_as"]) <= 4294967295
    prefix = ipaddress.IPv4Network(contract["allowed_prefix"])
    assert prefix.prefixlen < 32 and str(prefix) != "10.67.20.0/24"
workers = inventory["all"]["children"]["workers"]["hosts"]
computes = [host for host in workers.values() if "compute" in host.get("node_roles", [])]
assert computes and all("ovn_gateway" in host.get("node_roles", []) for host in computes)
router_ids = [str(ipaddress.IPv4Address(host["node_ip"])) for host in computes]
assert len(router_ids) == len(set(router_ids))
PY
then
  pass "production Phase 57 Rack BGP policy is approved and complete"
  ansible_playbook=${ANSIBLE_PLAYBOOK:-$infra_repo/.venv/bin/ansible-playbook}
  bgp_verifier=$infra_repo/automation/playbooks/57-verify-ovn-bgp-agent.yml
  if [[ -x "$ansible_playbook" && -f "$bgp_inventory" && -f "$bgp_verifier" ]] && \
     ANSIBLE_CONFIG="$repo_root/automation/ansible/ansible.cfg" \
     ANSIBLE_ROLES_PATH="$infra_repo/automation/roles:$repo_root/automation/ansible/roles" \
     "$ansible_playbook" -i "$bgp_inventory" "$bgp_verifier" >/dev/null 2>&1; then
    pass "live OVN BGP agents, FRR peers and active Rack /32 advertisements"
  else
    fail "live OVN BGP/FRR dataplane verification failed or has no active Rack /32"
  fi
else
  fail "production Phase 57 BGP inputs remain disabled, unapproved, or incomplete"
fi

printf 'SUMMARY failures=%d\n' "$failures"
[[ "$failures" -eq 0 ]]
