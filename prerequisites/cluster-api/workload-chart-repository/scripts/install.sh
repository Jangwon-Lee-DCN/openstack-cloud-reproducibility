#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repro_root="${REPRO_ROOT:-/home/ubuntu/openstack-cloud-reproducibility}"
repo_dir="${repro_root}/helm/repositories/magnum-workload"

test -f "${repo_dir}/index.yaml"
test -f "${repo_dir}/openstack-cluster-0.26.0.tgz"
grep -q \
  'http://magnum-chart-repository.openstack.svc.cluster.local/openstack-cluster-0.26.0.tgz' \
  "${repo_dir}/index.yaml"

kubectl -n openstack create configmap magnum-workload-chart-repository \
  --from-file="${repo_dir}/index.yaml" \
  --from-file="${repo_dir}/openstack-cluster-0.26.0.tgz" \
  --dry-run=client -o yaml |
  kubectl apply -f -

kubectl apply -f "${root}/manifests/repository.yaml"
kubectl -n openstack rollout restart deployment/magnum-chart-repository
kubectl -n openstack rollout status deployment/magnum-chart-repository \
  --timeout=5m
