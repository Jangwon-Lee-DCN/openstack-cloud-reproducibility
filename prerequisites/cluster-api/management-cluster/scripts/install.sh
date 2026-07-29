#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

kubectl -n cert-manager wait --for=condition=Available deployment/cert-manager --timeout=5m
python3 "${ROOT}/scripts/render.py" |
  kubectl apply --server-side --force-conflicts -f -
"${ROOT}/scripts/verify.sh"
