#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
namespace=${OPENSTACK_NAMESPACE:-openstack}
image=quay.io/airshipit/openstack-client@sha256:8a402a50ecf2afe14f580ad2bae17433605c29063b0d5e2c0f3d3c962d13c656
kubectl -n "$namespace" create configmap glance-image-freshness \
  --from-file=verify_image_freshness.py="$root/deploy/scripts/verify_image_freshness.py" \
  --from-file=catalog.yaml="$root/deploy/image-catalog/catalog.yaml" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: CronJob
metadata: {name: glance-image-freshness-audit, namespace: $namespace}
spec:
  schedule: "23 3 * * 1"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        metadata: {labels: {application: glance, component: image-freshness-audit}}
        spec:
          restartPolicy: Never
          automountServiceAccountToken: false
          nodeSelector: {openstack-control-plane: enabled}
          tolerations: [{key: node-role.kubernetes.io/control-plane, operator: Exists, effect: NoSchedule}]
          containers:
            - name: verify
              image: $image
              command: [python3, /opt/dcn/verify_image_freshness.py, /opt/dcn/catalog.yaml, --max-age-days, "45"]
              envFrom: [{secretRef: {name: keystone-keystone-admin}}]
              volumeMounts: [{name: source, mountPath: /opt/dcn, readOnly: true}]
              securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
          volumes: [{name: source, configMap: {name: glance-image-freshness, defaultMode: 0555}}]
EOF
