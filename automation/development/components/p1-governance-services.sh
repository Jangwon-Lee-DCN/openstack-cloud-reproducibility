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
    if ! kubectl -n "$DEVELOPMENT_NAMESPACE" get secret \
      governance-keystone-application-credential >/dev/null 2>&1; then
      bootstrap_port=15001
      kubectl -n openstack port-forward svc/keystone-api "$bootstrap_port:5000" \
        >"${TMPDIR:-/tmp}/governance-keystone-port-forward.log" 2>&1 &
      port_forward_pid=$!
      trap 'kill "$port_forward_pid" 2>/dev/null || true' EXIT
      ready=false
      for _ in 1 2 3 4 5; do
        if curl --fail --silent "http://127.0.0.1:$bootstrap_port/v3" >/dev/null; then ready=true; break; fi
        sleep 1
      done
      [[ $ready == true ]] || { echo 'Keystone bootstrap port-forward failed' >&2; exit 1; }
      kubectl -n openstack get secret keystone-keystone-admin -o json |
        DEVELOPMENT_NAMESPACE="$DEVELOPMENT_NAMESPACE" \
        GOVERNANCE_KEYSTONE_BOOTSTRAP_URL="http://127.0.0.1:$bootstrap_port" \
        GOVERNANCE_KEYSTONE_SERVICE_URL="http://keystone-api.openstack.svc.cluster.local:5000" \
        python3 "$root/services/governance-api/tools/provision_development_identity.py" |
        kubectl apply -f - >/dev/null
      kill "$port_forward_pid" 2>/dev/null || true
      trap - EXIT
    fi
    credential_revision=$(kubectl -n "$DEVELOPMENT_NAMESPACE" get secret \
      governance-keystone-application-credential -o jsonpath='{.metadata.resourceVersion}')
    helm upgrade --install governance "$chart" \
      --namespace "$DEVELOPMENT_NAMESPACE" \
      --values "$values" \
      --set-string "image.digest=$GOVERNANCE_IMAGE_DIGEST" \
      --set-string "workerImage.digest=$GOVERNANCE_WORKER_IMAGE_DIGEST" \
      --set-string "credentialRevision=$credential_revision" \
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
    python3 -c 'import json,sys; d=json.loads(sys.argv[1]); required={"keystone","opa","gnocchi","cloudkitty","barbican","designate","octavia","nova","cinder","neutron","glance","postgresql","rabbitmq"}; states={p["name"]:p for p in d["providers"]}; assert d["status"] == "ready"; assert all(states[n]["configured"] and states[n]["reachable"] for n in required)' "$readiness"
    policy_sha=$(kubectl -n vpc-control-plane-system get configmap opa-vpc-policy-v4 \
      -o jsonpath='{.data.policy\.rego}' | sha256sum | awk '{print $1}')
    [[ $policy_sha == 25774f220e1f6f301948aa7ebd0a681a0bf6bb012d132c0e0da619d93f4dad2c ]]
    opa_url="http://opa-pilot.vpc-control-plane-system.svc.cluster.local:8181/v1/data/vpc/authz/decision"
    allow=$(kubectl -n "$DEVELOPMENT_NAMESPACE" exec deployment/governance-api -c api -- \
      python3 -c 'import json,sys,urllib.request; body=json.dumps({"input":{"subject":{"roles":["member"]},"context":{"authorization_class":"project-write"}}}).encode(); print(json.load(urllib.request.urlopen(urllib.request.Request(sys.argv[1],data=body,headers={"Content-Type":"application/json"}),timeout=5))["result"]["allow"])' "$opa_url")
    deny=$(kubectl -n "$DEVELOPMENT_NAMESPACE" exec deployment/governance-api -c api -- \
      python3 -c 'import json,sys,urllib.request; body=json.dumps({"input":{"subject":{"roles":["reader"]},"context":{"authorization_class":"project-write"}}}).encode(); print(json.load(urllib.request.urlopen(urllib.request.Request(sys.argv[1],data=body,headers={"Content-Type":"application/json"}),timeout=5))["result"]["allow"])' "$opa_url")
    [[ $allow == True && $deny == False ]]
    rbac_answer=$(kubectl -n "$DEVELOPMENT_NAMESPACE" auth can-i create deployments \
      --as=system:serviceaccount:"$DEVELOPMENT_NAMESPACE":default 2>/dev/null || true)
    [[ $rbac_answer == no ]]
    ;;
  *) echo 'expected deploy or verify' >&2; exit 2 ;;
esac
