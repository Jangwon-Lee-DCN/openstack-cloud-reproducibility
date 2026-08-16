#!/usr/bin/env bash
set -euo pipefail

operation=${1:?deploy or verify}
: "${DEVELOPMENT_NAMESPACE:?development wrapper must set DEVELOPMENT_NAMESPACE}"
: "${DEVELOPMENT_NAME:?development wrapper must set DEVELOPMENT_NAME}"
[[ $DEVELOPMENT_NAME == p0-core-orchestration ]]
[[ $DEVELOPMENT_NAMESPACE == development-p0-core-orchestration ]]
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
manifest="$root/automation/development/manifests/p0-core-orchestration.yaml"
host=p0-core-orchestration.dev.dcn.ssu.ac.kr

case "$operation" in
  deploy)
    : "${CORE_ORCHESTRATOR_IMAGE:?set an immutable development image reference}"
    [[ $CORE_ORCHESTRATOR_IMAGE =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]] || {
      echo 'CORE_ORCHESTRATOR_IMAGE must be pinned by sha256 digest' >&2; exit 2;
    }
    if ! kubectl -n "$DEVELOPMENT_NAMESPACE" get secret p0-core-orchestration >/dev/null 2>&1; then
      kubectl -n "$DEVELOPMENT_NAMESPACE" create secret generic p0-core-orchestration \
        --from-literal=signing-key="$(openssl rand -hex 32)" \
        --from-literal=event-key="$(openssl rand -hex 32)"
    fi
    sed -e "s|__NAMESPACE__|$DEVELOPMENT_NAMESPACE|g" \
        -e "s|__IMAGE__|$CORE_ORCHESTRATOR_IMAGE|g" "$manifest" | kubectl apply -f -
    ;;
  verify)
    kubectl -n "$DEVELOPMENT_NAMESPACE" rollout status deployment/p0-core-orchestration --timeout=5m
    image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deploy p0-core-orchestration -o jsonpath='{.spec.template.spec.containers[0].image}')
    [[ $image =~ @sha256:[0-9a-f]{64}$ ]]
    worker_image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deploy p0-core-orchestration -o jsonpath='{.spec.template.spec.containers[1].image}')
    [[ $worker_image == "$image" ]]
    scheduler_image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deploy p0-core-orchestration -o jsonpath='{.spec.template.spec.containers[2].image}')
    [[ $scheduler_image == "$image" ]]
    node=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pod -l app.kubernetes.io/name=p0-core-orchestration -o jsonpath='{.items[0].spec.nodeName}')
    [[ $node == "${DEVELOPMENT_NODE:?}" ]]
    curl --fail --silent --show-error --insecure --connect-timeout 5 --max-time 15 \
      --resolve "$host:443:${DEVELOPMENT_GATEWAY_IP:?}" "https://$host/healthz" | grep -q '"status": "ok"'
    ;;
  *) echo "unsupported operation: $operation" >&2; exit 2 ;;
esac
