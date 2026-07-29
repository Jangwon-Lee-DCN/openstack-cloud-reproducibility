#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
namespace="${MAGNUM_NAMESPACE:-openstack}"
repro_root="${REPRO_ROOT:-/home/ubuntu/openstack-cloud-reproducibility}"
chart="${MAGNUM_CHART:-${repro_root}/helm/packages/patched/magnum-2026.1.0.tgz}"
site_values="${root}/values/site/magnum.yaml"
secret_values="${root}/secrets/magnum.values.sops.yaml"

test -f "${chart}"
sops filestatus "${secret_values}" | grep -q '"encrypted":true'

kubectl apply -f "${root}/../prerequisites/cluster-api/magnum-access/rbac.yaml"
"${root}/scripts/sync-internal-ca.sh"

helm upgrade --install magnum "${chart}" \
  --namespace "${namespace}" \
  --create-namespace \
  -f "${site_values}" \
  -f <(sops -d "${secret_values}") \
  --no-hooks \
  --timeout 15m

# The upstream chart declares bootstrap jobs as post-install hooks while API
# and conductor entrypoint dependencies wait for those jobs. Apply the hooks
# explicitly to avoid the first-install Helm wait cycle.
hooks=(
  "templates/job-db-init.yaml:magnum-db-init"
  "templates/job-db-sync.yaml:magnum-db-sync"
  "templates/job-rabbit-init.yaml:magnum-rabbit-init"
  "templates/job-ks-service.yaml:magnum-ks-service"
  "templates/job-ks-endpoints.yaml:magnum-ks-endpoints"
  "templates/job-ks-user.yaml:magnum-ks-user"
  "templates/job-ks-user-domain.yaml:magnum-domain-ks-user"
)

for item in "${hooks[@]}"; do
  template="${item%%:*}"
  job="${item##*:}"
  kubectl -n "${namespace}" delete job "${job}" --ignore-not-found --wait=true
  helm template magnum "${chart}" \
    --namespace "${namespace}" \
    -f "${site_values}" \
    -f <(sops -d "${secret_values}") \
    --show-only "${template}" |
    kubectl -n "${namespace}" apply -f -
  kubectl -n "${namespace}" wait "job/${job}" \
    --for=condition=Complete --timeout=10m
done

helm upgrade magnum "${chart}" \
  --namespace "${namespace}" \
  -f "${site_values}" \
  -f <(sops -d "${secret_values}") \
  --no-hooks \
  --wait \
  --timeout 15m

kubectl apply -f "${root}/manifests/openstack-public-routes.yaml"
kubectl apply -f \
  "${root}/../prerequisites/networking/openstack-internal-gateway/manifests/routes.yaml"
"${root}/../prerequisites/networking/openstack-internal-gateway/scripts/reconcile-catalog.sh"
"${root}/scripts/verify-magnum.sh"
