#!/usr/bin/env bash
set -euo pipefail
umask 077

NAMESPACE=${NAMESPACE:-openstack}
ADMIN_SECRET=${ADMIN_SECRET:-keystone-keystone-admin}
DEPLOY_LOCK=${DEPLOY_LOCK:-dcn-production-deploy-lock}
CHECK_POD="keystone-admin-auth-check-$$"

cleanup() {
  kubectl -n "$NAMESPACE" delete pod "$CHECK_POD" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

test -n "$(kubectl -n "$NAMESPACE" get configmap "$DEPLOY_LOCK" -o jsonpath='{.data.holder}')" || {
  echo "Keystone credential reconciliation requires the production deployment lock" >&2
  exit 1
}

create_check_pod() {
  kubectl -n "$NAMESPACE" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${CHECK_POD}
  labels: {application: keystone, component: admin-credential-check}
spec:
  restartPolicy: Never
  nodeSelector: {openstack-control-plane: enabled}
  tolerations:
    - {key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}
  containers:
    - name: openstack-client
      image: quay.io/airshipit/openstack-client:2026.1-ubuntu_noble
      command: [sleep, "300"]
      envFrom:
        - secretRef: {name: ${ADMIN_SECRET}}
EOF
  kubectl -n "$NAMESPACE" wait --for=condition=Ready "pod/$CHECK_POD" --timeout=2m >/dev/null
}

admin_authenticates() {
  kubectl -n "$NAMESPACE" exec "$CHECK_POD" -- openstack token issue >/dev/null 2>&1
}

create_check_pod
if admin_authenticates; then
  echo "Keystone administrator credential already matches the live identity backend."
  exit 0
fi

api_pod=$(kubectl -n "$NAMESPACE" get pods \
  -l application=keystone,component=api \
  --field-selector=status.phase=Running \
  -o jsonpath='{.items[0].metadata.name}')
test -n "$api_pod"

# Feed the canonical password only over stdin. It is never placed in a shell
# argument, temporary file, log, or Kubernetes object beyond its owning Secret.
kubectl -n "$NAMESPACE" get secret "$ADMIN_SECRET" -o jsonpath='{.data.OS_PASSWORD}' \
  | base64 -d \
  | kubectl -n "$NAMESPACE" exec -i "$api_pod" -c keystone-api -- python3 -c '
import sys
from keystone.server.wsgi import initialize_public_application
from keystone.common import provider_api

password = sys.stdin.read()
if not password:
    raise SystemExit("empty Keystone administrator password")
initialize_public_application()
identity = provider_api.ProviderAPIs.identity_api
user = identity.get_user_by_name("admin", "default")
identity.update_user(user["id"], {"password": password})
print("Keystone administrator credential synchronized through the identity backend.")
'

kubectl -n "$NAMESPACE" delete pod "$CHECK_POD" --wait=true >/dev/null
create_check_pod
admin_authenticates || {
  echo "Keystone administrator authentication still fails after synchronization" >&2
  exit 1
}
echo "Keystone administrator authentication verified."
