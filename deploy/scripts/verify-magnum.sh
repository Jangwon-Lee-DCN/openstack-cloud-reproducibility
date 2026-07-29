#!/usr/bin/env bash
set -euo pipefail

namespace="${MAGNUM_NAMESPACE:-openstack}"

kubectl -n "${namespace}" rollout status deployment/magnum-api --timeout=5m
kubectl -n "${namespace}" rollout status statefulset/magnum-conductor --timeout=5m

test "$(kubectl -n "${namespace}" get deployment magnum-api -o jsonpath='{.status.readyReplicas}')" = "2"
test "$(kubectl -n "${namespace}" get statefulset magnum-conductor -o jsonpath='{.status.readyReplicas}')" = "2"

for pdb in magnum-api magnum-conductor; do
  test "$(kubectl -n "${namespace}" get pdb "${pdb}" -o jsonpath='{.spec.minAvailable}')" = "1"
done

conductor="$(kubectl -n "${namespace}" get pod \
  -l application=magnum,component=conductor \
  -o jsonpath='{.items[0].metadata.name}')"
kubectl -n "${namespace}" exec "${conductor}" -- sh -lc \
  'python -c "import importlib.metadata as m; assert \"k8s_capi_helm_v1\" in [x.name for x in m.entry_points(group=\"magnum.drivers\")]; assert m.version(\"magnum-capi-helm\") == \"1.4.0\""'
kubectl -n "${namespace}" exec "${conductor}" -- \
  helm --kubeconfig /etc/magnum/kubeconfig.conf list -A >/dev/null

for route in openstack-public-services openstack-internal-services; do
  kubectl -n "${namespace}" wait "httproute/${route}" \
    --for='jsonpath={.status.parents[0].conditions[?(@.type=="Accepted")].status}=True' \
    --timeout=2m
  kubectl -n "${namespace}" wait "httproute/${route}" \
    --for='jsonpath={.status.parents[0].conditions[?(@.type=="ResolvedRefs")].status}=True' \
    --timeout=2m
done

code="$(curl -ksS --resolve api.internal.cloud.dcn.ssu.ac.kr:443:192.168.21.7 \
  -o /dev/null -w '%{http_code}' \
  https://api.internal.cloud.dcn.ssu.ac.kr/container-infra/v1/clusters)"
test "${code}" = "401"

echo "Magnum API, HA placement, CAPI driver, management-cluster access, and internal routing verified."
