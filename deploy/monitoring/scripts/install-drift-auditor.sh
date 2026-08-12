#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -gt 0 ]] || { echo "usage: install-drift-auditor.sh vpc-<project-id> [...]" >&2; exit 2; }
for namespace in "$@"; do
  [[ "$namespace" =~ ^vpc-[a-z0-9]([a-z0-9-]{0,57}[a-z0-9])?$ ]] || {
    echo "invalid project namespace: $namespace" >&2
    exit 2
  }
  kubectl get namespace "$namespace" >/dev/null
  kubectl -n "$namespace" get secret openstack-credentials >/dev/null || {
    echo "$namespace/openstack-credentials must contain the project-scoped clouds.yaml before scheduling audits" >&2
    exit 1
  }
  kubectl -n "${namespace}" create configmap vpc-neutron-drift-auditor \
    --from-file=audit.py="${root}/scripts/audit-vpc-neutron-drift.py" \
    --dry-run=client -o yaml | kubectl apply -f -
  sed "s/__PROJECT_NAMESPACE__/${namespace}/g" "${root}/manifests/neutron-drift-auditor-template.yaml" | kubectl apply -f -
  kubectl -n "$namespace" get cronjob vpc-neutron-drift-auditor -o jsonpath='{.spec.schedule}{"\n"}'
done
