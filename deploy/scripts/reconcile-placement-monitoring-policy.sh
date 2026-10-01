#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
mode=${1:-apply}
[[ "$mode" == apply || "$mode" == --check ]] || {
  echo "usage: $0 [--check]" >&2
  exit 2
}

"$root/deploy/scripts/verify-placement-monitoring-policy.sh"

if [[ "$mode" == --check ]]; then
  values=$(mktemp)
  trap 'shred -u "$values" 2>/dev/null || true' EXIT
  sops -d "$root/deploy/releases/placement.values.sops.yaml" |
    "$root/deploy/scripts/render-region-values.py" >"$values"
  helm template placement "$root/helm/packages/upstream/placement-2026.1.0.tgz" \
    --namespace openstack --include-crds --values "$values" |
    kubectl apply --dry-run=server -f - >/dev/null
  echo "Placement monitoring policy production render accepted"
  exit 0
fi

ONLY_RELEASE=placement VERIFY_AFTER_RECONCILE=0 \
  "$root/deploy/scripts/reconcile-full-stack.sh"
