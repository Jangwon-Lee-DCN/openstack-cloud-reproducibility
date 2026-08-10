#!/usr/bin/env bash
set -euo pipefail

TARGET_NS=openstack
TARGET_CONFIGMAP=openstack-internal-ca

work_dir="$(mktemp -d)"
cleanup() {
  rm -f "${work_dir}/internal-ca.crt" "${work_dir}/public-ca.crt" \
    "${work_dir}/ca.crt"
  rmdir "${work_dir}"
}
trap cleanup EXIT

kubectl -n openstack-internal-gateway-system get secret openstack-internal-ca \
  -o jsonpath='{.data.ca\.crt}' | base64 -d >"${work_dir}/internal-ca.crt"
if kubectl -n openstack-gateway-system get secret openstack-public-ca \
  >/dev/null 2>&1; then
  kubectl -n openstack-gateway-system get secret openstack-public-ca \
    -o jsonpath='{.data.ca\.crt}' | base64 -d >"${work_dir}/public-ca.crt"
else
  : >"${work_dir}/public-ca.crt"
fi
{
  cat "${work_dir}/internal-ca.crt"
  printf '\n'
  cat "${work_dir}/public-ca.crt"
  printf '\n'
} >"${work_dir}/ca.crt"
kubectl -n "${TARGET_NS}" create configmap "${TARGET_CONFIGMAP}" \
  --from-file=ca.crt="${work_dir}/ca.crt" \
  --dry-run=client -o yaml | kubectl apply -f -
