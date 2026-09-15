#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
chart="$root/charts/metrics-server-3.13.0.tgz"
values="$root/metrics-server/values/production.yaml"

test "$(sha256sum "$chart" | awk '{print $1}')" = \
  fb929902e3b7565663cdd1734f31d63735c932be1541a7228b5aeef6d2348a1f

helm upgrade --install metrics-server "$chart" \
  --namespace kube-system \
  --values "$values" \
  --wait --timeout 10m

kubectl -n kube-system rollout status deployment/metrics-server --timeout=5m
kubectl wait apiservice/v1beta1.metrics.k8s.io \
  --for=condition=Available --timeout=5m
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes >/dev/null
