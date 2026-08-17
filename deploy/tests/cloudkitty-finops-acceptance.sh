#!/usr/bin/env bash
set -euo pipefail

namespace=development-p1-governance-services

select_ready_pod() {
  local target_namespace=$1 selector=$2 required
  shift 2
  required=$(jq -cn '$ARGS.positional' --args "$@")
  kubectl -n "$target_namespace" get pod -l "$selector" -o json | jq -r --argjson required "$required" '
    [.items[] | . as $pod | select(.metadata.deletionTimestamp == null) |
      select(all($required[]; . as $name |
        any($pod.status.containerStatuses[]?; .name == $name and .ready))) |
      .metadata.name] | first // empty'
}

if [[ ${GOVERNANCE_FINOPS_SELECTOR_TEST:-0} == 1 ]]; then
  return 0 2>/dev/null || exit 0
fi

pod="$(select_ready_pod "$namespace" app.kubernetes.io/name=governance-api api worker)"
[[ -n "$pod" ]] || { echo 'no Ready non-terminating Governance pod for acceptance' >&2; exit 1; }

cleanup() {
  kubectl -n "$namespace" exec "$pod" -c worker -- \
    env GOVERNANCE_FINOPS_ACCEPTANCE=cleanup \
      GOVERNANCE_FINOPS_STATE_JSON="${acceptance_state:-}" \
      python -m governance_worker.acceptance >/dev/null 2>&1 || true
}
trap cleanup EXIT

seed=$(kubectl -n "$namespace" exec "$pod" -c worker -- \
  env GOVERNANCE_FINOPS_ACCEPTANCE=seed python -m governance_worker.acceptance)
acceptance_state=$seed
project_id=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["project_id"])' "$seed")
reset_timestamp=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["reset_timestamp"])' "$seed")
processor=$(select_ready_pod openstack application=cloudkitty,component=processor cloudkitty-processor)
[[ -n "$processor" ]] || { echo 'no Ready CloudKitty processor for acceptance processing' >&2; exit 1; }
# Acceptance-only synchronous processing uses CloudKitty's official Worker
# against the real configured collector, rater and storage. It deliberately
# does not reset/restart/reconfigure the production scheduler.
kubectl -n openstack exec "$processor" -c cloudkitty-processor -- python3 -c \
  'import datetime,sys; from cloudkitty import collector,service,storage; from cloudkitty.orchestrator import Worker; service.prepare_service(["finops-acceptance"], config_files=["/etc/cloudkitty/cloudkitty.conf"]); Worker(collector.get_collector(), storage.get_storage(), sys.argv[1], "finops-acceptance").do_execute_scope_processing(datetime.datetime.fromisoformat(sys.argv[2]))' \
  "$project_id" "$reset_timestamp"
acceptance_state=$(kubectl -n "$namespace" exec "$pod" -c worker -- \
  env GOVERNANCE_FINOPS_ACCEPTANCE=setup python -m governance_worker.acceptance
)
# Exercise persistence across a normal Kubernetes-managed replacement. Pod
# deletion is graceful (never forced), and the Deployment/PDB own recovery.
previous_pod=$pod
kubectl -n "$namespace" delete pod "$previous_pod" --wait=true --timeout=2m
kubectl -n "$namespace" rollout status deployment/governance-api --timeout=5m
pod="$(select_ready_pod "$namespace" app.kubernetes.io/name=governance-api api worker)"
[[ -n "$pod" && "$pod" != "$previous_pod" ]] || {
  echo 'Governance replacement pod did not become Ready' >&2
  exit 1
}
kubectl -n "$namespace" exec "$pod" -c worker -- \
  env GOVERNANCE_FINOPS_ACCEPTANCE=verify GOVERNANCE_FINOPS_STATE_JSON="$acceptance_state" \
    python -m governance_worker.acceptance
cleanup
trap - EXIT
