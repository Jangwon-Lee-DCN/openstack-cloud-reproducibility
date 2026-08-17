#!/usr/bin/env bash
set -euo pipefail
mode=${1:-apply}
[[ $mode == apply || $mode == verify ]] || { echo 'usage: reconcile-glance-image-catalog.sh apply|verify' >&2; exit 2; }
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
namespace=${OPENSTACK_NAMESPACE:-openstack}
job=glance-image-catalog
config=glance-image-catalog
image=quay.io/airshipit/openstack-client@sha256:8a402a50ecf2afe14f580ad2bae17433605c29063b0d5e2c0f3d3c962d13c656
kubectl -n "$namespace" create configmap "$config" \
  --from-file=glance_image_catalog.py="$root/deploy/scripts/glance_image_catalog.py" \
  --from-file=catalog.yaml="$root/deploy/image-catalog/catalog.yaml" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n "$namespace" delete job "$job" --ignore-not-found --wait=true >/dev/null
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: $job, namespace: $namespace}
spec:
  backoffLimit: 0
  template:
    metadata: {labels: {application: glance, component: image-catalog}}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      nodeSelector: {openstack-control-plane: enabled}
      tolerations: [{key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}]
      containers:
        - name: reconcile
          image: $image
          command: [python3, /opt/dcn/glance_image_catalog.py, $mode, /opt/dcn/catalog.yaml]
          envFrom: [{secretRef: {name: keystone-keystone-admin}}]
          volumeMounts: [{name: catalog, mountPath: /opt/dcn, readOnly: true}]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
      volumes:
        - name: catalog
          configMap: {name: $config, defaultMode: 0555}
EOF
for _ in $(seq 1 150); do
  complete=$(kubectl -n "$namespace" get job "$job" -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}')
  failed=$(kubectl -n "$namespace" get job "$job" -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}')
  [[ $complete == True ]] && break
  if [[ $failed == True ]]; then kubectl -n "$namespace" logs "job/$job" || true; exit 1; fi
  sleep 2
done
[[ ${complete:-} == True ]] || { kubectl -n "$namespace" logs "job/$job" || true; exit 1; }
kubectl -n "$namespace" logs "job/$job"
if [[ $mode == apply ]]; then
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: CronJob
metadata: {name: glance-image-catalog-audit, namespace: $namespace}
spec:
  schedule: "17 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 1
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        metadata: {labels: {application: glance, component: image-catalog-audit}}
        spec:
          restartPolicy: Never
          automountServiceAccountToken: false
          nodeSelector: {openstack-control-plane: enabled}
          tolerations: [{key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}]
          containers:
            - name: verify
              image: $image
              command: [python3, /opt/dcn/glance_image_catalog.py, verify, /opt/dcn/catalog.yaml]
              envFrom: [{secretRef: {name: keystone-keystone-admin}}]
              volumeMounts: [{name: catalog, mountPath: /opt/dcn, readOnly: true}]
              securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
          volumes:
            - name: catalog
              configMap: {name: $config, defaultMode: 0555}
EOF
fi
