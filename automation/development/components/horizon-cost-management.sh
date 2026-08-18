#!/usr/bin/env bash
set -euo pipefail

operation=${1:?deploy, verify, or rollback}
: "${DEVELOPMENT_NAMESPACE:?development wrapper must set DEVELOPMENT_NAMESPACE}"
: "${DEVELOPMENT_NAME:?development wrapper must set DEVELOPMENT_NAME}"
[[ $DEVELOPMENT_NAME == horizon-cost-management ]]
[[ $DEVELOPMENT_NAMESPACE == development-horizon-cost-management ]]
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)

case "$operation" in
  deploy)
    : "${HORIZON_COST_IMAGE_DIGEST:?set the tested sha256 digest}"
    [[ $HORIZON_COST_IMAGE_DIGEST =~ ^sha256:[a-f0-9]{64}$ ]]
    kubectl -n "$DEVELOPMENT_NAMESPACE" create configmap horizon-cost-acceptance \
      --from-file=acceptance.py="$root/deploy/tests/horizon_cost_management_acceptance.py" \
      --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl -n "$DEVELOPMENT_NAMESPACE" delete job horizon-cost-acceptance --ignore-not-found --wait=true >/dev/null
    sed "s|IMAGE_REF|registry.dcn.ssu.ac.kr/openstack/horizon@${HORIZON_COST_IMAGE_DIGEST}|" <<'EOF' | kubectl apply -f - >/dev/null
apiVersion: batch/v1
kind: Job
metadata: {name: horizon-cost-acceptance, namespace: development-horizon-cost-management}
spec:
  backoffLimit: 0
  template:
    metadata: {labels: {app: horizon-cost-acceptance}}
    spec:
      restartPolicy: Never
      priorityClassName: dcn-development-interruptible
      nodeSelector: {dcn.ssu.ac.kr/workload-class: development}
      tolerations:
        - {key: dcn.ssu.ac.kr/workload-class, operator: Equal, value: development, effect: NoSchedule}
        - {key: node-role.kubernetes.io/utility, operator: Equal, value: "true", effect: NoSchedule}
      containers:
        - name: test
          image: IMAGE_REF
          command: [python3, /tests/acceptance.py]
          volumeMounts: [{name: tests, mountPath: /tests, readOnly: true}]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
      volumes: [{name: tests, configMap: {name: horizon-cost-acceptance}}]
EOF
    ;;
  verify)
    kubectl -n "$DEVELOPMENT_NAMESPACE" wait --for=condition=complete job/horizon-cost-acceptance --timeout=5m
    kubectl -n "$DEVELOPMENT_NAMESPACE" logs job/horizon-cost-acceptance | grep -q '^PASS authenticated-equivalent'
    ;;
  rollback)
    kubectl -n "$DEVELOPMENT_NAMESPACE" delete job horizon-cost-acceptance --ignore-not-found --wait=true
    ;;
  *) exit 2 ;;
esac
