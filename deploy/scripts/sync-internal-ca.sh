#!/usr/bin/env bash
set -euo pipefail

SOURCE_NS=openstack-internal-gateway-system
SOURCE_SECRET=openstack-internal-ca
TARGET_NS=openstack
TARGET_CONFIGMAP=openstack-internal-ca

work_dir="$(mktemp -d)"
cleanup() {
  rm -f "${work_dir}/ca.crt"
  rmdir "${work_dir}"
}
trap cleanup EXIT

kubectl -n "${SOURCE_NS}" get secret "${SOURCE_SECRET}" \
  -o jsonpath='{.data.ca\.crt}' | base64 -d >"${work_dir}/ca.crt"
kubectl -n "${TARGET_NS}" create configmap "${TARGET_CONFIGMAP}" \
  --from-file=ca.crt="${work_dir}/ca.crt" \
  --dry-run=client -o yaml | kubectl apply -f -
