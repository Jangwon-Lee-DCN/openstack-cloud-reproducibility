#!/usr/bin/env bash
set -euo pipefail

NS=openstack-internal-gateway-system
kubectl -n "${NS}" wait --for=condition=Ready certificate/openstack-internal-tls --timeout=5m
kubectl -n "${NS}" wait --for=condition=Programmed gateway/openstack-internal-gateway --timeout=5m
test "$(kubectl -n "${NS}" get gateway openstack-internal-gateway -o jsonpath='{.status.addresses[0].value}')" = 10.67.10.7
test "$(kubectl -n "${NS}" get service cilium-gateway-openstack-internal-gateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')" = 10.67.10.7
kubectl -n openstack wait --for=jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}'=True httproute/openstack-internal-services --timeout=5m
CA_FILE="$(mktemp)"
trap 'rm -f "${CA_FILE}"' EXIT
kubectl -n "${NS}" get secret openstack-internal-ca -o jsonpath='{.data.ca\.crt}' | base64 -d >"${CA_FILE}"
curl --fail --silent --show-error --cacert "${CA_FILE}" \
  --resolve internal.cloud.dcn.ssu.ac.kr:443:10.67.10.7 \
  https://internal.cloud.dcn.ssu.ac.kr/identity/v3 >/dev/null
echo "VM-routable OpenStack internal API Gateway checks passed."
