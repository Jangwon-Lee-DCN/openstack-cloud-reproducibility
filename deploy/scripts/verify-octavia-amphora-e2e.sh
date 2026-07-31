#!/usr/bin/env bash

set -euo pipefail

lb="${OCTAVIA_AMPHORA_TEST_LB:-amphora-e2e-lb}"
subnet_id="${OCTAVIA_AMPHORA_TEST_SUBNET_ID:-ff1a30ad-2818-4859-9299-6be238ed975f}"

wait_active() {
  local phase=$1
  local status
  for attempt in $(seq 1 90); do
    status=$(openstack loadbalancer show "${lb}" -f value \
      -c provisioning_status)
    echo "phase=${phase} attempt=${attempt} status=${status}"
    [[ "${status}" == ACTIVE ]] && return 0
    [[ "${status}" == ERROR ]] && return 2
    sleep 5
  done
  return 3
}

if ! openstack loadbalancer show "${lb}" >/dev/null 2>&1; then
  openstack loadbalancer create \
    --name "${lb}" \
    --provider amphora \
    --vip-subnet-id "${subnet_id}" >/dev/null
  wait_active loadbalancer
fi

openstack server start octavia-backend-1 octavia-backend-2

if ! openstack loadbalancer listener show amphora-e2e-listener \
    >/dev/null 2>&1; then
  openstack loadbalancer listener create \
    --name amphora-e2e-listener \
    --protocol HTTP \
    --protocol-port 80 \
    "${lb}" >/dev/null
  wait_active listener
fi

if ! openstack loadbalancer pool show amphora-e2e-pool >/dev/null 2>&1; then
  openstack loadbalancer pool create \
    --name amphora-e2e-pool \
    --listener amphora-e2e-listener \
    --protocol HTTP \
    --lb-algorithm ROUND_ROBIN >/dev/null
  wait_active pool
fi

for entry in backend-1:10.42.0.74 backend-2:10.42.0.224; do
  name=${entry%%:*}
  address=${entry#*:}
  if ! openstack loadbalancer member show amphora-e2e-pool "${name}" \
      >/dev/null 2>&1; then
    openstack loadbalancer member create \
      --name "${name}" \
      --subnet-id "${subnet_id}" \
      --address "${address}" \
      --protocol-port 80 \
      amphora-e2e-pool >/dev/null
    wait_active "member-${name}"
  fi
done

vip_port=$(
  openstack loadbalancer show "${lb}" -f value -c vip_port_id
)
floating_ip=$(
  openstack floating ip list --port "${vip_port}" -f value \
    -c "Floating IP Address" | head -1
)
if [[ -z "${floating_ip}" ]]; then
  floating_ip=$(
    openstack floating ip create public --port "${vip_port}" -f value \
      -c floating_ip_address
  )
fi

echo "FLOATING_IP=${floating_ip}"
openstack loadbalancer status show "${lb}"
