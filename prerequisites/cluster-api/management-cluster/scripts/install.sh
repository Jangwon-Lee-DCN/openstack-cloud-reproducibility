#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

kubectl -n cert-manager wait --for=condition=Available deployment/cert-manager --timeout=5m
kubectl create namespace capo-system --dry-run=client -o yaml | kubectl apply -f -
kubectl -n openstack get secret telemetry-harbor-push -o json |
  jq '.metadata={name:"harbor-registry-pull",namespace:"capo-system"} |
      del(.status)' |
  kubectl apply -f -
python3 "${ROOT}/scripts/render.py" |
  kubectl apply --server-side --force-conflicts -f -
"${ROOT}/scripts/verify.sh"
