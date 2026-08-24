#!/usr/bin/env bash
set -euo pipefail

catalog=${DCN_SERVICE_CATALOG:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/config/tenant-service-catalog.yaml}
admin_project=${PREVIEW_ADMIN_PROJECT:-admin}
apply=${APPLY_PREVIEW_CATALOG:-false}

python3 - "$catalog" <<'PY'
import sys, yaml
value = yaml.safe_load(open(sys.argv[1]))
assert value["schema"] == "dcn.ssu.ac.kr/service-catalog/v1"
assert value["region"] == "seoul-ssu-1"
assert {v["status"] for v in value["services"].values()} <= {"ga", "preview", "unavailable"}
for name in ("baremetal-virtual", "gpu-passthrough"):
    assert value["services"][name]["status"] == "preview"
    assert value["services"][name]["audience"] == "admin"
print("valid tenant service catalog")
PY

if [[ "$apply" != true ]]; then
  echo "catalog validated; set APPLY_PREVIEW_CATALOG=true to reconcile private preview flavors"
  exit 0
fi

ensure_flavor() {
  local name=$1 ram=$2 disk=$3 vcpus=$4 output
  openstack flavor show "$name" >/dev/null 2>&1 ||
    openstack flavor create --private --ram "$ram" --disk "$disk" --vcpus "$vcpus" "$name"
  if ! output=$(openstack flavor set --project "$admin_project" "$name" 2>&1); then
    grep -Fq 'Flavor access already exists' <<<"$output" || {
      printf '%s\n' "$output" >&2
      return 1
    }
  fi
}

ensure_flavor bm.virtual.preview 2048 10 2
openstack flavor set bm.virtual.preview \
  --property resources:CUSTOM_BAREMETAL_VIRTUAL=1 \
  --property trait:CUSTOM_DCN_VIRTUAL_REDFISH=required

ensure_flavor gpu.passthrough.preview 8192 40 4
# Nova does not support changing an existing flavor's visibility. Fail closed
# below if an operator-created flavor with this reserved name is public.
for stale_property in \
  resources:CUSTOM_GPU \
  trait:CUSTOM_DCN_GPU_PASSTHROUGH_PREVIEW \
  hw:cpu_policy \
  hw:numa_nodes; do
  openstack flavor unset gpu.passthrough.preview \
    --property "$stale_property" 2>/dev/null || true
done
openstack flavor set gpu.passthrough.preview \
  --property 'pci_passthrough:alias=rtx3090ti:1,rtx3090ti-audio:1'

# A previously public or broadly granted Preview flavor must not retain access.
# Keep only the explicitly configured administrator project.
admin_project_id=$(openstack project show -f value -c id "$admin_project")
gpu_flavor_id=$(openstack flavor show -f value -c id gpu.passthrough.preview)
compute_endpoint=$(openstack endpoint list --service nova --interface internal \
  --region "${OS_REGION_NAME:?}" -f value -c URL | head -n1)
token=$(openstack token issue -f value -c id)
python3 - "$compute_endpoint" "$token" "$gpu_flavor_id" "$admin_project_id" <<'PY'
import json, sys, urllib.request
endpoint, token, flavor_id, admin_project_id = sys.argv[1:]
url = endpoint.rstrip("/") + "/flavors/" + flavor_id + "/os-flavor-access"
headers = {"Content-Type": "application/json", "X-Auth-Token": token}

def access_ids():
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return {item["tenant_id"] for item in json.load(response)["flavor_access"]}

for project_id in access_ids() - {admin_project_id}:
    request = urllib.request.Request(
        url,
        data=json.dumps({"removeTenantAccess": {"tenant": project_id}}).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status not in (200, 202):
            raise SystemExit(f"unexpected Nova flavor-access response: {response.status}")
if access_ids() != {admin_project_id}:
    raise SystemExit("GPU flavor access is not restricted to the administrator project")
PY
unset token

gpu_flavor_json=$(openstack flavor show -f json gpu.passthrough.preview)
[[ $(jq -r '."os-flavor-access:is_public"' <<<"$gpu_flavor_json") == false ]]
[[ $(jq -r '.properties["pci_passthrough:alias"]' <<<"$gpu_flavor_json") == \
  'rtx3090ti:1,rtx3090ti-audio:1' ]]

echo "private Preview flavors reconciled for project $admin_project"
