#!/usr/bin/env bash
set -euo pipefail
: "${DEVELOPMENT_NODE:?}"
: "${DEVELOPMENT_NAMESPACE:?}"
: "${DEVELOPMENT_GATEWAY_IP:?}"
: "${DEVELOPMENT_GATEWAY_DOMAIN:?}"

test "$(kubectl get node "$DEVELOPMENT_NODE" -o jsonpath='{.metadata.labels.dcn\.ssu\.ac\.kr/workload-class}')" = development
kubectl get node "$DEVELOPMENT_NODE" -o jsonpath='{.spec.taints}' | grep -q 'development'
test "$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pod -l app=development-smoke -o jsonpath='{.items[0].spec.nodeName}')" = "$DEVELOPMENT_NODE"
test "$(kubectl -n development-gateway-system get gateway development-gateway -o jsonpath='{.status.addresses[0].value}')" = "$DEVELOPMENT_GATEWAY_IP"
kubectl -n development-gateway-system wait --for=condition=Programmed gateway/development-gateway --timeout=5m
kubectl -n "$DEVELOPMENT_NAMESPACE" wait --for=condition=Accepted httproute/development-smoke --timeout=5m
kubectl -n "$DEVELOPMENT_NAMESPACE" wait --for=condition=ResolvedRefs httproute/development-smoke --timeout=5m
kubectl -n development-gateway-system wait --for=condition=Ready certificate/development-gateway-tls --timeout=5m

bad_dev="$(kubectl get pods -A -l '!job-name' -o json | jq -r --arg ns "$DEVELOPMENT_NAMESPACE" --arg node "$DEVELOPMENT_NODE" '.items[] | select(.metadata.namespace == $ns and .spec.nodeName != $node) | [.metadata.namespace,.metadata.name,.spec.nodeName] | @tsv')"
test -z "$bad_dev"

curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  --resolve "smoke.${DEVELOPMENT_GATEWAY_DOMAIN}:443:${DEVELOPMENT_GATEWAY_IP}" \
  --insecure "https://smoke.${DEVELOPMENT_GATEWAY_DOMAIN}/hostname" >/dev/null
