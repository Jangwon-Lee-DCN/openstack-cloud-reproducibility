#!/usr/bin/env bash
set -euo pipefail

namespace=${OPENSTACK_NAMESPACE:-openstack}
job=glance-image-rbac-acceptance
image=quay.io/airshipit/openstack-client@sha256:8a402a50ecf2afe14f580ad2bae17433605c29063b0d5e2c0f3d3c962d13c656
capi_id=${CAPI_IMAGE_ID:-a0b4466b-28d7-47e3-ae2e-67e5f8c983f3}
amphora_id=${AMPHORA_IMAGE_ID:-2613e5d6-3cdf-433f-a84b-e41507909ef5}

kubectl -n "$namespace" delete job "$job" --ignore-not-found --wait=true >/dev/null
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: $job, namespace: $namespace}
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 300
  template:
    metadata: {labels: {application: glance, component: image-rbac-acceptance}}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      nodeSelector: {openstack-control-plane: enabled}
      tolerations: [{key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}]
      containers:
        - name: verify
          image: $image
          envFrom: [{secretRef: {name: keystone-keystone-admin}}]
          env:
            - {name: CAPI_IMAGE_ID, value: "$capi_id"}
            - {name: AMPHORA_IMAGE_ID, value: "$amphora_id"}
          command: [bash, -ec]
          args:
            - |
              user="glance-rbac-\$(date +%s)"; password="Rbac!\$(date +%s)\$RANDOM"
              project=dcn; domain=dcn; owned_id=
              cleanup() {
                [[ -z "\$owned_id" ]] || openstack image delete "\$owned_id" >/dev/null 2>&1 || true
                [[ -z "\${user_id:-}" ]] || openstack user delete "\$user_id" >/dev/null 2>&1 || true
              }
              trap cleanup EXIT
              user_id=\$(openstack user create --domain "\$domain" --password "\$password" "\$user" -f value -c id)
              openstack role add --user "\$user_id" --user-domain "\$domain" --project "\$project" --project-domain "\$domain" member
              tenant=(--os-auth-url "\$OS_AUTH_URL" --os-auth-type password --os-username "\$user" --os-password "\$password" --os-user-domain-name "\$domain" --os-project-name "\$project" --os-project-domain-name "\$domain" --os-region-name seoul-ssu-1)
              owned_id=\$(openstack "\${tenant[@]}" image create "rbac-owned-\$(date +%s)" --private --disk-format raw --container-format bare -f value -c id)
              openstack "\${tenant[@]}" image set --property rbac_acceptance=passed "\$owned_id"
              openstack "\${tenant[@]}" image delete "\$owned_id"; owned_id=
              if openstack "\${tenant[@]}" image set --property dcn_support_status=recommended "\$CAPI_IMAGE_ID" >/tmp/capi.out 2>&1; then
                echo 'FAIL: tenant modified a provider CAPI image'; exit 1
              fi
              if openstack "\${tenant[@]}" image delete "\$CAPI_IMAGE_ID" >/tmp/delete.out 2>&1; then
                echo 'FAIL: tenant deleted a protected provider CAPI image'; exit 1
              fi
              if openstack "\${tenant[@]}" image show "\$AMPHORA_IMAGE_ID" >/tmp/amphora.out 2>&1; then
                echo 'FAIL: tenant read the private hidden Amphora image'; exit 1
              fi
              echo 'PASS: own image create/modify/delete allowed'
              echo 'PASS: provider CAPI modify/delete denied'
              echo 'PASS: private hidden Amphora lookup denied'
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
EOF
kubectl -n "$namespace" wait --for=condition=complete "job/$job" --timeout=6m || {
  kubectl -n "$namespace" logs "job/$job" || true; exit 1;
}
kubectl -n "$namespace" logs "job/$job"
