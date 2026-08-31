#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-openstack}
KEYCLOAK_NAMESPACE=${KEYCLOAK_NAMESPACE:-keycloak}
PLAYWRIGHT_IMAGE='mcr.microsoft.com/playwright:v1.54.2-noble@sha256:18b4bcff4f8ba0ac8c44b09f09def6a4f6cb8579e5f26381c21f38b50935d5d8'
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
suffix=$(date +%s)-$RANDOM
username="dcn-login-acceptance-$suffix"
password=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
user_id=

kc_host=keycloak-service.keycloak.svc.cluster.local
kc_ip=$(kubectl -n "$KEYCLOAK_NAMESPACE" get service keycloak-service -o jsonpath='{.spec.clusterIP}')
kc_user=$(kubectl -n "$KEYCLOAK_NAMESPACE" get secret keycloak-bootstrap-admin -o jsonpath='{.data.username}' | base64 -d)
kc_pass=$(kubectl -n "$KEYCLOAK_NAMESPACE" get secret keycloak-bootstrap-admin -o jsonpath='{.data.password}' | base64 -d)
kc_curl=(curl -fsS --resolve "$kc_host:8080:$kc_ip")
token=$(${kc_curl[@]} -X POST "http://$kc_host:8080/realms/master/protocol/openid-connect/token" \
  -d client_id=admin-cli -d "username=$kc_user" -d "password=$kc_pass" -d grant_type=password | jq -r .access_token)

cleanup() {
  kubectl -n "$NAMESPACE" delete job unified-login-production-browser --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kubectl -n "$NAMESPACE" delete configmap unified-login-production-browser --ignore-not-found >/dev/null 2>&1 || true
  if [[ -n "$user_id" ]]; then
    ${kc_curl[@]} -X DELETE -H "Authorization: Bearer $token" \
      "http://$kc_host:8080/admin/realms/dcn/users/$user_id" >/dev/null 2>&1 || true
  fi
  unset password kc_pass token
}
trap cleanup EXIT

payload=$(jq -nc --arg u "$username" --arg p "$password" '{username:$u,email:($u+"@acceptance.invalid"),firstName:"DCN",lastName:"Acceptance",enabled:true,emailVerified:true,requiredActions:[],credentials:[{type:"password",value:$p,temporary:false}]}')
${kc_curl[@]} -X POST -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d "$payload" "http://$kc_host:8080/admin/realms/dcn/users" >/dev/null
user_id=$(${kc_curl[@]} -H "Authorization: Bearer $token" \
  "http://$kc_host:8080/admin/realms/dcn/users?username=$username&exact=true" | jq -er '.[0].id')
group_id=$(${kc_curl[@]} -H "Authorization: Bearer $token" \
  "http://$kc_host:8080/admin/realms/dcn/groups?search=openstack-members&exact=true" | jq -er '.[] | select(.name=="openstack-members") | .id')
${kc_curl[@]} -X PUT -H "Authorization: Bearer $token" \
  "http://$kc_host:8080/admin/realms/dcn/users/$user_id/groups/$group_id" >/dev/null

kubectl -n "$NAMESPACE" create configmap unified-login-production-browser \
  --from-file=test.js="$ROOT/deploy/scripts/verify-unified-login-browser.js" \
  --from-file=package.json="$ROOT/deploy/tests/unified-login-package.json" \
  --from-file=package-lock.json="$ROOT/deploy/tests/unified-login-package-lock.json" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$NAMESPACE" delete job unified-login-production-browser --ignore-not-found --wait=true >/dev/null
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: unified-login-production-browser, namespace: $NAMESPACE}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      nodeSelector: {kubernetes.io/hostname: dcn-1a-compute-0}
      hostAliases:
        - ip: "10.67.10.6"
          hostnames: [cloud.dcn.ssu.ac.kr, billing.dcn.ssu.ac.kr]
        - ip: "10.67.10.5"
          hostnames: [platform.dcn.ssu.ac.kr]
        - ip: "10.67.10.4"
          hostnames: [registry.dcn.ssu.ac.kr]
      securityContext: {runAsNonRoot: true, runAsUser: 1000, runAsGroup: 1000, fsGroup: 1000, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: browser
          image: $PLAYWRIGHT_IMAGE
          command: [/bin/bash, -ec]
          args: ["cp /acceptance/* /runtime/; cd /runtime; npm ci --ignore-scripts --no-audit --no-fund; node test.js"]
          env:
            - {name: PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD, value: "1"}
            - {name: TEST_USERNAME, value: "$username"}
            - {name: TEST_PASSWORD, value: "$password"}
          volumeMounts: [{name: test, mountPath: /acceptance, readOnly: true}, {name: runtime, mountPath: /runtime}]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true}
      volumes: [{name: test, configMap: {name: unified-login-production-browser}}, {name: runtime, emptyDir: {}}]
EOF
if ! kubectl -n "$NAMESPACE" wait --for=condition=complete job/unified-login-production-browser --timeout=8m; then
  kubectl -n "$NAMESPACE" logs job/unified-login-production-browser || true
  exit 1
fi
kubectl -n "$NAMESPACE" logs job/unified-login-production-browser | grep -qx production-unified-login-browser-e2e-passed
