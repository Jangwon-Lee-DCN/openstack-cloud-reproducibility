#!/usr/bin/env bash
set -euo pipefail

operation=${1:?deploy or verify}
: "${DEVELOPMENT_NAMESPACE:?}"
: "${DEVELOPMENT_NAME:?}"
[[ "$DEVELOPMENT_NAME" == "p1-resilience-operations" ]] || { echo "unexpected development component" >&2; exit 2; }
[[ "$DEVELOPMENT_NAMESPACE" == "development-p1-resilience-operations" ]] || { echo "unsafe namespace: $DEVELOPMENT_NAMESPACE" >&2; exit 2; }

root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
manifest="$root/automation/development/manifests/p1-resilience-operations.yaml"

case "$operation" in
  deploy)
    : "${P1_RESILIENCE_IMAGE:?set immutable image reference registry/repository@sha256:digest}"
    [[ "$P1_RESILIENCE_IMAGE" =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]] || { echo "P1_RESILIENCE_IMAGE must be immutable" >&2; exit 2; }
    sed -e "s|__NAMESPACE__|$DEVELOPMENT_NAMESPACE|g" -e "s|__IMAGE__|$P1_RESILIENCE_IMAGE|g" "$manifest" | kubectl apply -f -
    ;;
  verify)
    kubectl -n "$DEVELOPMENT_NAMESPACE" rollout status deployment/p1-resilience-operations --timeout=5m
    kubectl -n "$DEVELOPMENT_NAMESPACE" get pod -l app=p1-resilience-operations -o jsonpath='{range .items[*]}{.spec.nodeSelector.dcn\.ssu\.ac\.kr/workload-class}{"\n"}{end}' | grep -qx development
    kubectl -n "$DEVELOPMENT_NAMESPACE" get deployment p1-resilience-operations -o jsonpath='{.spec.template.spec.containers[0].image}' | grep -Eq '@sha256:[0-9a-f]{64}$'
    pod=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pod -l app=p1-resilience-operations -o jsonpath='{.items[0].metadata.name}')
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import urllib.request; assert b"fake/v1alpha1" in urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=3).read()'
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8080/openapi.json", timeout=3)); assert d["openapi"] == "3.1.0" and "/v1/backup-policies" in d["paths"]'
    # API must reject identity-free requests at the application boundary.
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import urllib.error,urllib.request; u="http://127.0.0.1:8080/v1/runs/backup-run"; r=urllib.request.Request(u,data=b"{}",method="POST"); exec("try:\n urllib.request.urlopen(r)\n raise SystemExit(1)\nexcept urllib.error.HTTPError as e:\n assert e.code == 401")'
    ;;
  *) exit 2 ;;
esac
