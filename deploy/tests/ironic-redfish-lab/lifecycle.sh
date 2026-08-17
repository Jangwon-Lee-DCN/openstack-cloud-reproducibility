#!/usr/bin/env bash
set -euo pipefail

[[ ${IRONIC_VIRTUAL_LIFECYCLE_CONFIRMATION:-} == ERASE_VIRTUAL_LAB_NODE ]] || {
  echo "set IRONIC_VIRTUAL_LIFECYCLE_CONFIRMATION=ERASE_VIRTUAL_LAB_NODE" >&2
  exit 2
}
node=${IRONIC_LAB_NODE:-ironic-redfish-node-0}
image=${IRONIC_LAB_IMAGE:-}
checksum=${IRONIC_LAB_IMAGE_CHECKSUM:-}
[[ -n "$image" && -n "$checksum" ]] || { echo "IRONIC_LAB_IMAGE and checksum are required" >&2; exit 2; }

state=$(openstack baremetal node show "$node" -f value -c provision_state)
if [[ "$state" == active ]]; then
  openstack baremetal node undeploy "$node"
  openstack baremetal node wait --provision-state available --timeout 900 "$node"
elif [[ "$state" != available ]]; then
  echo "$node must be available or active, got $state" >&2
  exit 1
fi

openstack baremetal node deploy "$node" --image "$image" --instance-info image_checksum="$checksum"
openstack baremetal node wait --provision-state active --timeout 1200 "$node"
openstack baremetal node show "$node" -f value -c last_error | grep -qx None
openstack baremetal node undeploy "$node"
openstack baremetal node wait --provision-state available --timeout 900 "$node"
openstack baremetal node show "$node" -f value -c last_error | grep -qx None
echo "virtual Redfish deploy/undeploy lifecycle passed"
