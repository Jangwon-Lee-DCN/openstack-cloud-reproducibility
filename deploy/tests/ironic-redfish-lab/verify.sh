#!/usr/bin/env bash
set -euo pipefail

namespace="${OPENSTACK_NAMESPACE:-openstack}"
node_name="${IRONIC_LAB_NODE:-ironic-redfish-node-0}"
redfish_address="${REDFISH_ADDRESS:-http://192.168.21.10:8000}"
client_pod="${IRONIC_LAB_CLIENT_POD:-ironic-lab-client}"
client_image="${OPENSTACK_CLIENT_IMAGE:-quay.io/airshipit/openstack-client:2026.1-ubuntu_noble}"

system_path="$(
  curl -fsS "${redfish_address}/redfish/v1/Systems" |
    jq -r '.Members[0]["@odata.id"]'
)"
test -n "${system_path}"
curl -fsS "${redfish_address}${system_path}" >/dev/null

for conductor in ironic-conductor-0 ironic-conductor-1; do
  kubectl -n "${namespace}" exec "${conductor}" -c ironic-conductor -- \
    python3 -c \
    "import urllib.request; assert urllib.request.urlopen('${redfish_address}${system_path}', timeout=5).status == 200"
done

created_client=false
if ! kubectl -n "${namespace}" get pod "${client_pod}" \
  -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null |
  grep -qx true; then
  kubectl -n "${namespace}" delete pod "${client_pod}" \
    --ignore-not-found --wait=true >/dev/null
  kubectl -n "${namespace}" run "${client_pod}" \
    --restart=Never \
    --image="${client_image}" \
    --overrides="$(
      jq -nc --arg name "${client_pod}" --arg image "${client_image}" \
        '{spec:{containers:[{name:$name,image:$image,
          envFrom:[{secretRef:{name:"keystone-keystone-admin"}}],
          command:["sleep","600"]}]}}'
    )"
  kubectl -n "${namespace}" wait --for=condition=Ready \
    "pod/${client_pod}" --timeout=120s
  created_client=true
fi

cleanup() {
  if "${created_client}"; then
    kubectl -n "${namespace}" delete pod "${client_pod}" \
      --ignore-not-found --wait=true >/dev/null
  fi
}
trap cleanup EXIT

osc=(
  kubectl -n "${namespace}" exec "${client_pod}" --
  env -u OS_PROJECT_NAME -u OS_PROJECT_ID OS_SYSTEM_SCOPE=all
  openstack
)

"${osc[@]}" baremetal node show "${node_name}" \
  -f yaml -c uuid -c driver -c provision_state -c power_state \
  -c conductor -c properties -c last_error
"${osc[@]}" baremetal node validate "${node_name}" -f yaml

test "$("${osc[@]}" baremetal node show "${node_name}" -f value -c last_error)" = "None"
provision_state="$(
  "${osc[@]}" baremetal node show "${node_name}" \
    -f value -c provision_state
)"
case "${provision_state}" in
  manageable|available|active) ;;
  *)
    echo "Unexpected provision state: ${provision_state}" >&2
    exit 1
    ;;
esac

if [[ "${provision_state}" == active ]]; then
  test "$(virsh -c qemu:///session domstate "${node_name}")" = running
  test "$(virsh -c qemu:///session domblklist "${node_name}" --details |
    awk '$2 == "disk" {count++} END {print count+0}')" = 1
  ping -c 1 -W 2 172.31.250.100 >/dev/null
fi

echo "Ironic virtual Redfish lab verification passed."
