#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for namespace in "$@"; do
  kubectl -n "${namespace}" create configmap vpc-neutron-drift-auditor \
    --from-file=audit.py="${root}/scripts/audit-vpc-neutron-drift.py" \
    --dry-run=client -o yaml | kubectl apply -f -
  sed "s/__PROJECT_NAMESPACE__/${namespace}/g" "${root}/manifests/neutron-drift-auditor-template.yaml" | kubectl apply -f -
done
