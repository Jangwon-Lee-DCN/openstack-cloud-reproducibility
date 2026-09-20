#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
namespace=${CINDER_ACCEPTANCE_NAMESPACE:-openstack}
image_id=${CINDER_ACCEPTANCE_IMAGE_ID:?}
client_image=${OPENSTACK_CLIENT_IMAGE:-quay.io/airshipit/openstack-client@sha256:8a402a50ecf2afe14f580ad2bae17433605c29063b0d5e2c0f3d3c962d13c656}
name="cinder-image-cache-acceptance-$(date +%s)"; configmap="${name}-script"
cleanup() {
  kubectl -n "${namespace}" delete job "${name}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
  kubectl -n "${namespace}" delete configmap "${configmap}" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT
kubectl -n "${namespace}" create configmap "${configmap}" --from-file=run.sh="${root}/deploy/acceptance/cinder-image-volume-cache.sh"
kubectl -n "${namespace}" apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: ${name}}
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 2700
  template:
    spec:
      restartPolicy: Never
      nodeSelector: {openstack-control-plane: enabled}
      tolerations:
        - {key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}
      containers:
        - name: acceptance
          image: ${client_image}
          command: [/bin/bash, /opt/acceptance/run.sh]
          envFrom:
            - secretRef: {name: keystone-keystone-admin}
          env:
            - {name: CINDER_ACCEPTANCE_IMAGE_ID, value: "${image_id}"}
            - {name: CINDER_ACCEPTANCE_VOLUME_TYPE, value: "${CINDER_ACCEPTANCE_VOLUME_TYPE:-general-purpose}"}
            - {name: CINDER_ACCEPTANCE_VOLUME_SIZE_GB, value: "${CINDER_ACCEPTANCE_VOLUME_SIZE_GB:-5}"}
            - {name: CINDER_ACCEPTANCE_TIMEOUT_SECONDS, value: "${CINDER_ACCEPTANCE_TIMEOUT_SECONDS:-1200}"}
          volumeMounts:
            - {name: script, mountPath: /opt/acceptance, readOnly: true}
      volumes:
        - name: script
          configMap: {name: ${configmap}, defaultMode: 0555}
EOF
deadline=$(( $(date +%s) + 2700 ))
while true; do
  succeeded=$(kubectl -n "${namespace}" get job "${name}" -o jsonpath='{.status.succeeded}')
  failed=$(kubectl -n "${namespace}" get job "${name}" -o jsonpath='{.status.failed}')
  [[ "${succeeded:-0}" -ge 1 ]] && break
  if [[ "${failed:-0}" -ge 1 || $(date +%s) -ge ${deadline} ]]; then
    kubectl -n "${namespace}" logs "job/${name}" --all-containers=true || true
    exit 1
  fi
  sleep 5
done
kubectl -n "${namespace}" logs "job/${name}" --all-containers=true
