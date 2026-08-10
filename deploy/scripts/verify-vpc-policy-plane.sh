#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=vpc-control-plane-system
declare -A selectors=(
  [vpc-control-plane-controller-manager]='control-plane=controller-manager'
  [vpc-facade]='app.kubernetes.io/name=vpc-facade'
  [opa-pilot]='app.kubernetes.io/name=opa-vpc-shadow'
)
for deployment in vpc-control-plane-controller-manager vpc-facade opa-pilot; do
  test "$(kubectl -n "$NAMESPACE" get deployment "$deployment" -o jsonpath='{.status.readyReplicas}')" = 2
  test "$(kubectl -n "$NAMESPACE" get pods -l "${selectors[$deployment]}" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l)" -ge 2
done
test "$(kubectl -n "$NAMESPACE" get configmap opa-vpc-policy-v4 -o jsonpath='{.metadata.labels.app\.kubernetes\.io/version}')" = vpc-authz-v4
test "$(kubectl -n "$NAMESPACE" get configmap vpc-facade-opa-enforcement -o jsonpath='{.data.classes}')" = read,project-write,network-sharing,security-policy

port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
kubectl -n "$NAMESPACE" port-forward service/opa-pilot "$port:8181" >/dev/null 2>&1 &
forward_pid=$!
cleanup() { kill "$forward_pid" 2>/dev/null || true; wait "$forward_pid" 2>/dev/null || true; }
trap cleanup EXIT
for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:$port/health" >/dev/null && break; sleep 1; done

allow=$(curl -sf -H 'Content-Type: application/json' -d '{"input":{"subject":{"roles":["reader"]},"context":{"authorization_class":"read"}}}' \
  "http://127.0.0.1:$port/v1/data/vpc/authz/decision" | python3 -c 'import json,sys; print(str(json.load(sys.stdin)["result"]["allow"]).lower())')
deny=$(curl -sf -H 'Content-Type: application/json' -d '{"input":{"subject":{"roles":["reader"]},"context":{"authorization_class":"project-write"}}}' \
  "http://127.0.0.1:$port/v1/data/vpc/authz/decision" | python3 -c 'import json,sys; print(str(json.load(sys.stdin)["result"]["allow"]).lower())')
test "$allow" = true
test "$deny" = false
echo "VPC control plane HA and OPA vpc-authz-v4 allow/deny checks passed."
