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
    : "${GOVERNANCE_WORKER_IMAGE_DIGEST:?set the development-tested worker sha256 image digest}"
    [[ $GOVERNANCE_IMAGE_DIGEST =~ ^sha256:[a-f0-9]{64}$ ]] || {
      echo 'GOVERNANCE_IMAGE_DIGEST must be sha256:<64 lowercase hex>' >&2
      exit 2
    }
    [[ $GOVERNANCE_WORKER_IMAGE_DIGEST =~ ^sha256:[a-f0-9]{64}$ ]] || {
      echo 'GOVERNANCE_WORKER_IMAGE_DIGEST must be sha256:<64 lowercase hex>' >&2
      exit 2
    }
    # Development-only Rabbit connection: copy the already least-privilege
    # Ceilometer bus credential without decoding or printing it. This Secret is
    # namespace-local and is removed with the development namespace.
    kubectl -n openstack get secret ceilometer-rabbitmq-user -o json |
      jq --arg namespace "$DEVELOPMENT_NAMESPACE" '
        {apiVersion:"v1",kind:"Secret",
         metadata:{name:"governance-real-integrations",namespace:$namespace},
         type:"Opaque",data:{"rabbitmq-url":((.data.RABBITMQ_CONNECTION|@base64d|
           sub("^rabbit://";"amqp://")|sub(":15672/";":5672/"))|@base64)}}' |
      kubectl apply -f - >/dev/null
    helm upgrade --install governance "$chart" \
      --namespace "$DEVELOPMENT_NAMESPACE" \
      --values "$values" \
      --set-string "image.digest=$GOVERNANCE_IMAGE_DIGEST" \
      --set-string "workerImage.digest=$GOVERNANCE_WORKER_IMAGE_DIGEST" \
      --wait --timeout 5m --atomic
    ;;
  verify)
    kubectl -n "$DEVELOPMENT_NAMESPACE" rollout status deployment/governance-api --timeout=5m
    kubectl -n "$DEVELOPMENT_NAMESPACE" rollout status statefulset/governance-postgresql --timeout=5m
    actual_images=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get deployment governance-api \
      -o jsonpath='{range .spec.template.spec.containers[*]}{.image}{"\n"}{end}')
    [[ $(grep -c '@sha256:' <<<"$actual_images") == 2 ]] || {
      echo "mutable or missing image deployed: $actual_images" >&2
      exit 1
    }
    nodes=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get pods -l app.kubernetes.io/name=governance-api \
      -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}')
    [[ -n $nodes ]] && [[ $(sort -u <<<"$nodes") == dcn-1b-utility-0 ]] || {
      echo "governance pod escaped development node: $nodes" >&2
      exit 1
    }
    curl --fail --silent --show-error --insecure --connect-timeout 5 --max-time 15 \
      --resolve "$host:443:$DEVELOPMENT_GATEWAY_IP" "https://$host/healthz" |
      python3 -c 'import json,sys; assert json.load(sys.stdin) == {"status":"ok"}'
    readiness=$(curl --silent --show-error --insecure --connect-timeout 5 --max-time 15 \
      --resolve "$host:443:$DEVELOPMENT_GATEWAY_IP" "https://$host/readyz")
    python3 -c 'import json,sys; d=json.loads(sys.argv[1]); required={"keystone","gnocchi","barbican","designate","octavia","postgresql","rabbitmq"}; states={p["name"]:p for p in d["providers"]}; assert d["status"] == "ready"; assert all(states[n]["configured"] and states[n]["reachable"] for n in required); assert states["opa"]["configured"]' "$readiness"
    kubectl -n "$DEVELOPMENT_NAMESPACE" auth can-i create deployments \
      --as=system:serviceaccount:"$DEVELOPMENT_NAMESPACE":default | grep -qx no
    ;;
  *) echo 'expected deploy or verify' >&2; exit 2 ;;
esac
