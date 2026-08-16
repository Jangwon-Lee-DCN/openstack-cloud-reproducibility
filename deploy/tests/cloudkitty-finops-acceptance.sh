#!/usr/bin/env bash
set -euo pipefail

namespace=development-p1-governance-services
pod="$(kubectl -n "$namespace" get pod -l app.kubernetes.io/name=governance-api \
  -o jsonpath='{.items[0].metadata.name}')"
[[ -n "$pod" ]]

cleanup() {
  kubectl -n "$namespace" exec "$pod" -c worker -- \
    env GOVERNANCE_FINOPS_ACCEPTANCE=cleanup python -m governance_worker.acceptance >/dev/null 2>&1 || true
}
trap cleanup EXIT

kubectl -n "$namespace" exec "$pod" -c worker -- \
  env GOVERNANCE_FINOPS_ACCEPTANCE=setup python -m governance_worker.acceptance
before="$(kubectl -n "$namespace" get pod "$pod" -o jsonpath='{.status.containerStatuses[?(@.name=="worker")].restartCount}')"
kubectl -n "$namespace" exec "$pod" -c worker -- kill 1 || true
for _ in $(seq 1 60); do
  after="$(kubectl -n "$namespace" get pod "$pod" -o jsonpath='{.status.containerStatuses[?(@.name=="worker")].restartCount}')"
  ready="$(kubectl -n "$namespace" get pod "$pod" -o jsonpath='{.status.containerStatuses[?(@.name=="worker")].ready}')"
  [[ "$after" -gt "$before" && "$ready" == true ]] && break
  sleep 2
done
[[ "$after" -gt "$before" && "$ready" == true ]]
kubectl -n "$namespace" exec "$pod" -c worker -- \
  env GOVERNANCE_FINOPS_ACCEPTANCE=verify python -m governance_worker.acceptance
cleanup
trap - EXIT
