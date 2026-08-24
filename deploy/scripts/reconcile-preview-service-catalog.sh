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
while read -r project_id; do
  [[ -z "$project_id" || "$project_id" == "$admin_project_id" ]] && continue
  openstack flavor unset --project "$project_id" gpu.passthrough.preview
done < <(openstack flavor access list -f value -c 'Project ID' gpu.passthrough.preview)

[[ $(openstack flavor show -f value -c 'Is Public' gpu.passthrough.preview) == False ]]
mapfile -t gpu_access < <(openstack flavor access list -f value -c 'Project ID' gpu.passthrough.preview)
[[ ${#gpu_access[@]} -eq 1 && ${gpu_access[0]} == "$admin_project_id" ]]
[[ $(openstack flavor show -f json gpu.passthrough.preview | jq -r '.properties["pci_passthrough:alias"]') == \
  'rtx3090ti:1,rtx3090ti-audio:1' ]]

echo "private Preview flavors reconciled for project $admin_project"
