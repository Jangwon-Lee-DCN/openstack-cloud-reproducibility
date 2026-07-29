#!/usr/bin/env bash
set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

kubectl get gatewayclass cilium >/dev/null
kubectl get clusterissuer selfsigned-temporary >/dev/null
kubectl apply -f "${STACK_DIR}/manifests/namespace.yaml"
kubectl apply -f "${STACK_DIR}/manifests/lb-ip-pool.yaml"
kubectl apply -f "${STACK_DIR}/manifests/tls-temporary-selfsigned.yaml"
kubectl apply -f "${STACK_DIR}/manifests/gateway.yaml"
kubectl apply -f "${STACK_DIR}/manifests/routes.yaml"
"${STACK_DIR}/scripts/verify.sh"
