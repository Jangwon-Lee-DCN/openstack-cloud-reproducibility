#!/usr/bin/env bash
set -euo pipefail

if [[ "${APPROVE_RECONCILE:-}" != "yes" ]]; then
  echo "Refusing to mutate a resource. Re-run with APPROVE_RECONCILE=yes after reviewing the drift report." >&2
  exit 2
fi
if [[ $# -ne 3 ]]; then
  echo "usage: APPROVE_RECONCILE=yes $0 <namespace> <resource> <name>" >&2
  exit 2
fi

namespace=$1
resource=$2
name=$3
case "$resource" in
  securitygroup|elasticip|natgateway) ;;
  *) echo "resource must be securitygroup, elasticip, or natgateway" >&2; exit 2 ;;
esac

kubectl -n "$namespace" annotate "$resource" "$name" \
  "vpc.dcn.ssu.ac.kr/operator-reconcile-requested-at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --overwrite
