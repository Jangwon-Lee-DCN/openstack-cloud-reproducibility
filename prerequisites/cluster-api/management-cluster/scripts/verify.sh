#!/usr/bin/env bash
set -euo pipefail

deployments=(
  capi-system/capi-controller-manager
  capi-kubeadm-bootstrap-system/capi-kubeadm-bootstrap-controller-manager
  capi-kubeadm-control-plane-system/capi-kubeadm-control-plane-controller-manager
  capo-system/capo-controller-manager
  orc-system/orc-controller-manager
)

for item in "${deployments[@]}"; do
  namespace="${item%%/*}"
  deployment="${item##*/}"
  kubectl -n "${namespace}" rollout status "deployment/${deployment}" --timeout=10m
  test "$(kubectl -n "${namespace}" get deployment "${deployment}" -o jsonpath='{.status.readyReplicas}')" = 2
  test "$(kubectl -n "${namespace}" get pdb "${deployment}" -o jsonpath='{.spec.minAvailable}')" = 1
  test "$(kubectl -n "${namespace}" get pods -l control-plane -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l)" -ge 2
done

kubectl get crd \
  clusters.cluster.x-k8s.io \
  openstackclusters.infrastructure.cluster.x-k8s.io \
  images.openstack.k-orc.cloud
echo "CAPI core, kubeadm providers, CAPO and ORC HA checks passed."
