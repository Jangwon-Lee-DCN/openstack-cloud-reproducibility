#!/usr/bin/env bash
set -euo pipefail
umask 077

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
namespace=governance-system
release=governance
: "${GOVERNANCE_IMAGE_DIGEST:?immutable API digest required}"
: "${GOVERNANCE_WORKER_IMAGE_DIGEST:?immutable worker digest required}"
[[ $GOVERNANCE_IMAGE_DIGEST =~ ^sha256:[a-f0-9]{64}$ ]]
[[ $GOVERNANCE_WORKER_IMAGE_DIGEST =~ ^sha256:[a-f0-9]{64}$ ]]

lock_namespace=openstack
lock_name=dcn-production-deploy-lock
holder="$(hostname)-governance-$$-$(date +%s)"
cleanup() {
  if [[ $(kubectl -n "$lock_namespace" get configmap "$lock_name" -o jsonpath='{.data.holder}' 2>/dev/null || true) == "$holder" ]]; then
    kubectl -n "$lock_namespace" delete configmap "$lock_name" --ignore-not-found --wait=false >/dev/null
  fi
}
trap cleanup EXIT
kubectl -n "$lock_namespace" create configmap "$lock_name" \
  --from-literal="holder=$holder" --from-literal=release=governance >/dev/null || {
    echo 'another production reconciliation owns the deployment lock' >&2
    exit 1
  }

kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl label namespace "$namespace" pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/audit=restricted pod-security.kubernetes.io/warn=restricted --overwrite >/dev/null

webhook_key=$(openssl rand -hex 32)
kubectl -n openstack get secret ceilometer-rabbitmq-user -o json |
  jq --arg namespace "$namespace" --arg webhook_key "$webhook_key" '
    {apiVersion:"v1",kind:"Secret",metadata:{name:"governance-real-integrations",namespace:$namespace},
     type:"Opaque",data:{"rabbitmq-url":((.data.RABBITMQ_CONNECTION|@base64d|
       sub("^rabbit://";"amqp://")|sub(":15672/";":5672/"))|@base64),
       "webhook-signing-key":($webhook_key|@base64)}}' | kubectl apply -f - >/dev/null

bootstrap_port=15002
kubectl -n openstack port-forward svc/keystone-api "$bootstrap_port:5000" \
  >"${TMPDIR:-/tmp}/governance-production-keystone-port-forward.log" 2>&1 &
port_forward_pid=$!
trap 'kill "$port_forward_pid" 2>/dev/null || true; cleanup' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10; do
  curl -fsS "http://127.0.0.1:$bootstrap_port/v3" >/dev/null && break
  sleep 1
done
kubectl -n openstack get secret keystone-keystone-admin -o json |
  GOVERNANCE_NAMESPACE="$namespace" GOVERNANCE_IDENTITY_NAME=governance-production \
  GOVERNANCE_IDENTITY_DESCRIPTION='Production Governance provider integration' \
  GOVERNANCE_KEYSTONE_BOOTSTRAP_URL="http://127.0.0.1:$bootstrap_port" \
  GOVERNANCE_KEYSTONE_SERVICE_URL='http://keystone-api.openstack.svc.cluster.local:5000' \
  python3 "$root/services/governance-api/tools/provision_development_identity.py" |
  kubectl apply -f - >/dev/null
kill "$port_forward_pid" 2>/dev/null || true
trap cleanup EXIT

revision=$(kubectl -n "$namespace" get secret governance-keystone-application-credential -o jsonpath='{.metadata.resourceVersion}')
helm upgrade --install "$release" "$root/helm/governance" -n "$namespace" \
  -f "$root/helm/governance/production-values.yaml" \
  --set-string image.digest="$GOVERNANCE_IMAGE_DIGEST" \
  --set-string workerImage.digest="$GOVERNANCE_WORKER_IMAGE_DIGEST" \
  --set-string credentialRevision="$revision" --atomic --wait --timeout 10m

kubectl -n "$namespace" rollout status deployment/governance-api --timeout=5m
kubectl -n "$namespace" rollout status statefulset/governance-postgresql --timeout=5m
readiness=$(kubectl -n "$namespace" exec deployment/governance-api -c api -- \
  python3 -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/readyz",timeout=10).read().decode())')
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); required={"keystone","opa","gnocchi","cloudkitty","barbican","designate","octavia","nova","cinder","neutron","glance","postgresql","rabbitmq"}; p={x["name"]:x for x in d["providers"]}; assert d["status"]=="ready"; assert all(p[n]["configured"] and p[n]["reachable"] for n in required)' "$readiness"
echo 'production Governance API reconciliation PASS'
