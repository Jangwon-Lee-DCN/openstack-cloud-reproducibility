#!/usr/bin/env bash
set -euo pipefail

if [[ "${OCTAVIA_JOBBOARD_FAILOVER_TEST:-}" != YES ]]; then
  echo "Set OCTAVIA_JOBBOARD_FAILOVER_TEST=YES to create an Amphora LB and delete its active worker Pod." >&2
  exit 2
fi

namespace="${OCTAVIA_NAMESPACE:-openstack}"
lb="${OCTAVIA_JOBBOARD_TEST_LB:-jobboard-failover-e2e}"
subnet_id="${OCTAVIA_AMPHORA_TEST_SUBNET_ID:-ff1a30ad-2818-4859-9299-6be238ed975f}"
start_time=$(date -u +%Y-%m-%dT%H:%M:%SZ)
revision_before=$(helm -n "${namespace}" history octavia -o json |
  python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["revision"])')

for pod in $(
  kubectl -n "${namespace}" get pod \
    -l application=octavia,component=worker -o name
); do
  kubectl -n "${namespace}" exec "${pod}" -c octavia-worker -- \
    grep -q '^jobboard_enabled = true$' /etc/octavia/octavia.conf
  kubectl -n "${namespace}" exec "${pod}" -c octavia-worker -- \
    python3 -c 'from redis.sentinel import Sentinel'
done

kubectl -n "${namespace}" exec valkey-node-0 -c sentinel -- \
  valkey-cli -p 26379 SENTINEL ckquorum octavia-jobboard |
  grep -q '^OK 3 usable Sentinels'

if openstack loadbalancer show "${lb}" >/dev/null 2>&1; then
  echo "Refusing to reuse existing load balancer ${lb}." >&2
  exit 3
fi

lb_id=$(
  openstack loadbalancer create \
    --name "${lb}" \
    --provider amphora \
    --vip-subnet-id "${subnet_id}" \
    -f value -c id
)
echo "loadbalancer=${lb_id}"

victim=""
for attempt in $(seq 1 90); do
  for pod in $(
    kubectl -n "${namespace}" get pod \
      -l application=octavia,component=worker -o name
  ); do
    if kubectl -n "${namespace}" logs "${pod}" -c octavia-worker \
        --since-time="${start_time}" 2>/dev/null | grep -q "${lb_id}"; then
      victim=${pod#pod/}
      break 2
    fi
  done
  sleep 1
done
test -n "${victim}"

victim_node=$(
  kubectl -n "${namespace}" get pod "${victim}" \
    -o jsonpath='{.spec.nodeName}'
)
echo "deleting_worker=${victim} node=${victim_node}"
kubectl -n "${namespace}" delete pod "${victim}" --wait=false

for attempt in $(seq 1 120); do
  provisioning=$(
    openstack loadbalancer show "${lb_id}" \
      -f value -c provisioning_status
  )
  operating=$(
    openstack loadbalancer show "${lb_id}" \
      -f value -c operating_status
  )
  echo "attempt=${attempt} provisioning=${provisioning} operating=${operating}"
  [[ "${provisioning}" == ERROR ]] && exit 4
  if [[ "${provisioning}" == ACTIVE && "${operating}" == ONLINE ]]; then
    break
  fi
  sleep 10
done
[[ "${provisioning}" == ACTIVE && "${operating}" == ONLINE ]]

revision_after=$(helm -n "${namespace}" history octavia -o json |
  python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["revision"])')
test "${revision_before}" = "${revision_after}"

amphora_count=$(
  openstack loadbalancer amphora list \
    --loadbalancer "${lb_id}" -f value -c id | wc -l
)
test "${amphora_count}" -eq 2
echo "Jobboard worker-failover verification passed."
