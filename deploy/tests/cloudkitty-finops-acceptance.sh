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

seed=$(kubectl -n "$namespace" exec "$pod" -c worker -- \
  env GOVERNANCE_FINOPS_ACCEPTANCE=seed python -m governance_worker.acceptance)
project_id=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["project_id"])' "$seed")
reset_timestamp=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["reset_timestamp"])' "$seed")
processor=$(kubectl -n openstack get pod -l application=cloudkitty,component=processor -o json |
  jq -r '[.items[] | select(.metadata.deletionTimestamp == null) |
    select(any(.status.containerStatuses[]?; .name == "cloudkitty-processor" and .ready)) |
    .metadata.name] | first // empty')
[[ -n "$processor" ]] || { echo 'no Ready CloudKitty processor for acceptance reset' >&2; exit 1; }
kubectl -n openstack exec "$processor" -c cloudkitty-processor -- python3 -c \
  'import datetime,sys; from cloudkitty import service; service.prepare_service(["finops-acceptance"], config_files=["/etc/cloudkitty/cloudkitty.conf"]); from cloudkitty.storage_state import StateManager; StateManager().set_last_processed_timestamp(sys.argv[1], datetime.datetime.fromisoformat(sys.argv[2]))' \
  "$project_id" "$reset_timestamp"
# Processor scope discovery sleeps for the configured collection period. A
# rollout after the supported state reset makes the dedicated acceptance scope
# discoverable immediately without shortening production rating periods.
kubectl -n openstack rollout restart deployment/cloudkitty-processor >/dev/null
kubectl -n openstack rollout status deployment/cloudkitty-processor --timeout=5m
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
