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
    kubectl -n "$DEVELOPMENT_NAMESPACE" get deployment p1-resilience-operations -o jsonpath='{.spec.template.metadata.labels.dcn\.ssu\.ac\.kr/central-opa-client}' | grep -qx allowed
    pod=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pod -l app=p1-resilience-operations -o jsonpath='{.items[0].metadata.name}')
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=3)); assert d["mode"] == "integration" and d["track_a"] == "real/v1alpha1"'
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8080/openapi.json", timeout=3)); assert d["openapi"] == "3.1.0" and "/v1/backup-policies" in d["paths"]'
    # API must reject identity-free requests at the application boundary.
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import urllib.error,urllib.request; u="http://127.0.0.1:8080/v1/runs/backup-run"; r=urllib.request.Request(u,data=b"{}",method="POST"); exec("try:\n urllib.request.urlopen(r)\n raise SystemExit(1)\nexcept urllib.error.HTTPError as e:\n assert e.code == 401")'
    # Provider readiness remains independently fail-closed. This Track C
    # consumer gate requires the two cross-track contracts, not unrelated RGW
    # data-plane reachability from the controller namespace.
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import json,urllib.error,urllib.request; exec("try:\n d=json.load(urllib.request.urlopen(\"http://127.0.0.1:8080/v1/capabilities\",timeout=20))\nexcept urllib.error.HTTPError as e:\n assert e.code==503; d=json.load(e)"); assert d["destructive_actions"]=="fenced" and len(d["services"])==9 and d["track_a_url"]["reachable"] and d["track_b_url"]["reachable"] and d["track_a_url"]["contract_write"]=="canonical-v1alpha1" and d["track_b_url"]["contract_write"]=="canonical-v1alpha1"'
    # Durable delivery schema is the restart/idempotency boundary for both consumers.
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import os,sqlite3; db=sqlite3.connect(os.environ["RESILIENCE_DB"]); cols={r[1] for r in db.execute("pragma table_info(deliveries)")}; assert {"target","delivery_key","state","attempts","last_error","response_json"}.issubset(cols)'
    # Central OPA must allow the shared read class, deny a privileged class for
    # an ordinary member, and the client must turn denial into a hard failure.
    kubectl -n "$DEVELOPMENT_NAMESPACE" exec "$pod" -- python -c 'import os; from dcn_resilience.integrations import OPAClient,IntegrationError; c=OPAClient(os.environ["OPA_URL"]); assert c.decide({"roles":["member"]},"read",{"type":"resilience-capability"})["allow"]; exec("try:\n c.decide({\"roles\":[\"member\"]},\"network-sharing\",{\"type\":\"resilience-capability\"})\n raise SystemExit(1)\nexcept IntegrationError:\n pass")'
    ;;
  *) exit 2 ;;
esac
