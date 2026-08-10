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
  'python -c "import importlib.metadata as m; names=[x.name for x in m.entry_points(group=\"magnum.drivers\")]; assert \"k8s_capi_helm_v1\" in names; assert \"k8s_capi_gitops_v1\" in names; assert m.version(\"magnum-capi-helm\") == \"1.4.0\"; assert m.version(\"magnum-capi-gitops\") == \"0.1.0\""'
kubectl -n "${namespace}" exec "${conductor}" -- \
  helm --kubeconfig /etc/magnum/kubeconfig.conf list -A >/dev/null

kubectl -n "${namespace}" wait httproute/openstack-internal-services \
  --for='jsonpath={.status.parents[0].conditions[?(@.type=="Accepted")].status}=True' \
  --timeout=2m

# The public Gateway is an independent production acceptance gate. Validate
# its route only when that Gateway has actually been provisioned.
if kubectl -n openstack-gateway-system get gateway openstack-gateway >/dev/null 2>&1; then
  kubectl -n "${namespace}" wait httproute/openstack-public-services \
    --for='jsonpath={.status.parents[0].conditions[?(@.type=="Accepted")].status}=True' \
    --timeout=2m
fi

code="$(curl -ksS --resolve internal.cloud.dcn.ssu.ac.kr:443:10.67.10.7 \
  -o /dev/null -w '%{http_code}' \
  https://internal.cloud.dcn.ssu.ac.kr/container-infra/v1/clusters)"
test "${code}" = "401"

echo "Magnum API, HA placement, CAPI driver, management-cluster access, and internal routing verified."
