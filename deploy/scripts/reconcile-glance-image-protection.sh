#!/usr/bin/env bash
set -euo pipefail

mode=${1:-apply}
case "$mode" in apply|verify|rollback) ;; *) echo 'usage: reconcile-glance-image-protection.sh apply|verify|rollback' >&2; exit 2 ;; esac
if [[ $mode == rollback && ${APPROVE_GLANCE_IMAGE_UNPROTECT:-} != yes ]]; then
  echo 'rollback requires APPROVE_GLANCE_IMAGE_UNPROTECT=yes' >&2
  exit 2
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
namespace=${OPENSTACK_NAMESPACE:-openstack}
job=glance-image-protection
config=glance-image-protection
image=quay.io/airshipit/openstack-client@sha256:8a402a50ecf2afe14f580ad2bae17433605c29063b0d5e2c0f3d3c962d13c656

kubectl -n "$namespace" create configmap "$config" \
  --from-file=glance_image_protection.py="$root/deploy/scripts/glance_image_protection.py" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$namespace" delete job "$job" --ignore-not-found --wait=true >/dev/null
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $job
  namespace: $namespace
spec:
  backoffLimit: 0
  template:
    metadata:
      labels: {application: glance, component: image-protection}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      nodeSelector: {openstack-control-plane: enabled}
      tolerations:
        - {key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}
      containers:
        - name: reconcile
          image: $image
          command: [python3, /opt/dcn/glance_image_protection.py, $mode]
          envFrom:
            - secretRef: {name: keystone-keystone-admin}
          env:
            - {name: APPROVE_GLANCE_IMAGE_UNPROTECT, value: "${APPROVE_GLANCE_IMAGE_UNPROTECT:-no}"}
          volumeMounts:
            - {name: script, mountPath: /opt/dcn, readOnly: true}
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
            runAsNonRoot: true
            runAsUser: 65534
            seccompProfile: {type: RuntimeDefault}
      volumes:
        - name: script
          configMap: {name: $config, defaultMode: 0555}
EOF

if ! kubectl -n "$namespace" wait --for=condition=complete "job/$job" --timeout=5m; then
  kubectl -n "$namespace" logs "job/$job" || true
  exit 1
fi
kubectl -n "$namespace" logs "job/$job"
