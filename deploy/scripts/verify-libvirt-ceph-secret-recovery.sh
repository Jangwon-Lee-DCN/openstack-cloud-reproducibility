#!/usr/bin/env bash
set -euo pipefail

namespace=${NAMESPACE:-openstack}
selector=${LIBVIRT_SELECTOR:-application=libvirt,component=libvirt}
secret_uuid=${LIBVIRT_CEPH_SECRET_UUID:-457eb676-33da-42ec-9a8c-9293d545c337}
exercise=false

if [[ ${1:-} == "--exercise-repair" ]]; then
  exercise=true
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--exercise-repair]" >&2
  exit 2
fi

pod=$(kubectl -n "${namespace}" get pod -l "${selector}" \
  -o jsonpath='{.items[0].metadata.name}')
[[ -n ${pod} ]]

secret_exists() {
  kubectl -n "${namespace}" exec "${pod}" -c libvirt -- virsh secret-list |
    awk 'NR > 2 {print $1}' | grep -Fxq "${secret_uuid}"
}

if ! secret_exists; then
  echo "FAIL: libvirt Ceph secret ${secret_uuid} is absent before verification" >&2
  exit 1
fi
echo "PASS: libvirt Ceph secret ${secret_uuid} is present"

if ! ${exercise}; then
  echo "INFO: use --exercise-repair to undefine the secret and verify automatic restoration"
  exit 0
fi

kubectl -n "${namespace}" exec "${pod}" -c libvirt -- \
  virsh secret-undefine "${secret_uuid}" >/dev/null
echo "INFO: deliberately undefined ${secret_uuid}; waiting for the watchdog"

for attempt in $(seq 1 12); do
  sleep 10
  if secret_exists; then
    echo "PASS: watchdog restored ${secret_uuid} after attempt ${attempt}"
    exit 0
  fi
done

echo "FAIL: watchdog did not restore ${secret_uuid} within 120 seconds" >&2
exit 1
