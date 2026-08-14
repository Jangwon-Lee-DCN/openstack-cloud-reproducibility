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
# Generic keystoneauth clients normalize /identity/v3 to the origin-root /v3.
# Assert that compatibility path during every reproducible phase execution;
# checking only the catalog URL missed the Horizon project-token failure.
curl --fail --silent --show-error --cacert "${CA_FILE}" \
  --resolve internal.cloud.dcn.ssu.ac.kr:443:10.67.10.7 \
  https://internal.cloud.dcn.ssu.ac.kr/v3 >/dev/null
# Nova may require a token even for version discovery. A 401 proves the route
# reached Nova; the regression was the Gateway-generated 404 before routing.
nova_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --cacert "${CA_FILE}" \
  --resolve internal.cloud.dcn.ssu.ac.kr:443:10.67.10.7 \
  https://internal.cloud.dcn.ssu.ac.kr/v2.1)"
case "${nova_status}" in 200|300|401) ;; *) echo "unexpected Nova /v2.1 status: ${nova_status}" >&2; exit 1;; esac
echo "VM-routable OpenStack internal API Gateway checks passed."
