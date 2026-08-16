#!/usr/bin/env bash
set -euo pipefail
umask 077

operation=${1:?deploy or verify}
: "${DEVELOPMENT_NAMESPACE:?development wrapper must set DEVELOPMENT_NAMESPACE}"
: "${DEVELOPMENT_NAME:?development wrapper must set DEVELOPMENT_NAME}"
: "${DEVELOPMENT_GATEWAY_IP:?development wrapper must set DEVELOPMENT_GATEWAY_IP}"
[[ $DEVELOPMENT_NAME == p1-governance-services ]]
[[ $DEVELOPMENT_NAMESPACE == development-p1-governance-services ]]

root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
chart="$root/helm/governance"
values="$chart/development-values.yaml"
host=p1-governance-services.dev.dcn.ssu.ac.kr

case "$operation" in
  deploy)
    : "${GOVERNANCE_IMAGE_DIGEST:?set the development-tested sha256 image digest}"
    [[ $GOVERNANCE_IMAGE_DIGEST =~ ^sha256:[a-f0-9]{64}$ ]] || {
      echo 'GOVERNANCE_IMAGE_DIGEST must be sha256:<64 lowercase hex>' >&2
      exit 2
    }
    helm upgrade --install governance "$chart" \
      --namespace "$DEVELOPMENT_NAMESPACE" \
      --values "$values" \
      --set-string "image.digest=$GOVERNANCE_IMAGE_DIGEST" \
      --wait --timeout 5m --atomic
    ;;
  verify)
    kubectl -n "$DEVELOPMENT_NAMESPACE" rollout status deployment/governance-api --timeout=5m
    actual_image=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deployment governance-api \
      -o jsonpath='{.spec.template.spec.containers[0].image}')
    [[ $actual_image == *@sha256:* ]] || { echo "mutable image deployed: $actual_image" >&2; exit 1; }
    nodes=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pods -l app.kubernetes.io/name=governance-api \
      -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}')
    [[ -n $nodes ]] && [[ $(sort -u <<<"$nodes") == dcn-1b-utility-0 ]] || {
      echo "governance pod escaped development node: $nodes" >&2
      exit 1
    }
    curl --fail --silent --show-error --insecure --connect-timeout 5 --max-time 15 \
      --resolve "$host:443:$DEVELOPMENT_GATEWAY_IP" "https://$host/healthz" |
      python3 -c 'import json,sys; assert json.load(sys.stdin) == {"status":"ok"}'
    kubectl -n "$DEVELOPMENT_NAMESPACE" auth can-i create deployments \
      --as=system:serviceaccount:"$DEVELOPMENT_NAMESPACE":default | grep -qx no
    ;;
  *) echo 'expected deploy or verify' >&2; exit 2 ;;
esac
