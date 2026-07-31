#!/usr/bin/env bash
#
# Reconcile the cloud-side resources required by the Octavia Amphora provider.
# Run this script inside an OpenStack client container with admin credentials.

set -euo pipefail

MGMT_NETWORK="${OCTAVIA_MGMT_NETWORK:-lb-mgmt-net}"
MGMT_SUBNET="${OCTAVIA_MGMT_SUBNET:-lb-mgmt-subnet}"
MGMT_CIDR="${OCTAVIA_MGMT_CIDR:-172.31.255.0/24}"
MGMT_POOL_START="${OCTAVIA_MGMT_POOL_START:-172.31.255.10}"
MGMT_POOL_END="${OCTAVIA_MGMT_POOL_END:-172.31.255.250}"
AMPHORA_FLAVOR="${OCTAVIA_AMPHORA_FLAVOR:-m1.amphora}"
AMPHORA_KEYPAIR="${OCTAVIA_AMPHORA_KEYPAIR:-octavia-key}"

if ! openstack network show "${MGMT_NETWORK}" >/dev/null 2>&1; then
  openstack network create "${MGMT_NETWORK}" >/dev/null
fi

if ! openstack subnet show "${MGMT_SUBNET}" >/dev/null 2>&1; then
  openstack subnet create \
    --network "${MGMT_NETWORK}" \
    --subnet-range "${MGMT_CIDR}" \
    --allocation-pool "start=${MGMT_POOL_START},end=${MGMT_POOL_END}" \
    "${MGMT_SUBNET}" >/dev/null
fi

if ! openstack security group show lb-mgmt-sec-grp >/dev/null 2>&1; then
  openstack security group create lb-mgmt-sec-grp >/dev/null
  openstack security group rule create --protocol tcp --dst-port 9443 \
    lb-mgmt-sec-grp >/dev/null
  openstack security group rule create --protocol icmp \
    lb-mgmt-sec-grp >/dev/null
fi

if ! openstack security group show lb-health-mgr-sec-grp >/dev/null 2>&1; then
  openstack security group create lb-health-mgr-sec-grp >/dev/null
  openstack security group rule create --protocol udp --dst-port 5555 \
    lb-health-mgr-sec-grp >/dev/null
fi

if ! openstack security group show lb-worker-sec-grp >/dev/null 2>&1; then
  openstack security group create lb-worker-sec-grp >/dev/null
fi

controller_ip_port_list=""
for node in cloud-controller-0 cloud-controller-1; do
  hm_port="octavia-health-manager-port-${node}"
  worker_port="octavia-worker-port-${node}"

  if ! openstack port show "${hm_port}" >/dev/null 2>&1; then
    openstack port create \
      --network "${MGMT_NETWORK}" \
      --security-group lb-health-mgr-sec-grp \
      --device-owner Octavia:health-mgr \
      --host "${node}" \
      "${hm_port}" >/dev/null
  fi

  if ! openstack port show "${worker_port}" >/dev/null 2>&1; then
    openstack port create \
      --network "${MGMT_NETWORK}" \
      --security-group lb-worker-sec-grp \
      --device-owner Octavia:worker \
      --host "${node}" \
      "${worker_port}" >/dev/null
  fi

  hm_ip="$(
    openstack port show "${hm_port}" -f json |
      python3 -c 'import json,sys; print(json.load(sys.stdin)["fixed_ips"][0]["ip_address"])'
  )"
  if [[ -n "${controller_ip_port_list}" ]]; then
    controller_ip_port_list+=","
  fi
  controller_ip_port_list+="${hm_ip}:5555"
done

if ! openstack flavor show "${AMPHORA_FLAVOR}" >/dev/null 2>&1; then
  openstack flavor create --ram 1024 --disk 3 --vcpus 1 \
    "${AMPHORA_FLAVOR}" >/dev/null
fi

# The keypair is intentionally created without retaining its private key. It
# satisfies Nova's key-name contract while disabling routine SSH access to
# service-owned Amphora appliances.
if ! openstack keypair show "${AMPHORA_KEYPAIR}" >/dev/null 2>&1; then
  openstack keypair create "${AMPHORA_KEYPAIR}" >/dev/null
fi

network_id="$(openstack network show "${MGMT_NETWORK}" -f value -c id)"
flavor_id="$(openstack flavor show "${AMPHORA_FLAVOR}" -f value -c id)"
security_group_id="$(
  openstack security group show lb-mgmt-sec-grp -f value -c id
)"

cat <<EOF
OCTAVIA_AMP_BOOT_NETWORK_LIST=${network_id}
OCTAVIA_AMP_FLAVOR_ID=${flavor_id}
OCTAVIA_AMP_SECGROUP_LIST=${security_group_id}
OCTAVIA_HM_CONTROLLER_IP_PORT_LIST=${controller_ip_port_list}
EOF
