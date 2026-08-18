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
      initContainers:
        - name: prepare-secret-key-store
          image: IMAGE_REF
          command: [sh, -c, 'touch /state/store /state/store.lock']
          volumeMounts: [{name: state, mountPath: /state}]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: test
          image: IMAGE_REF
          command: [python3, /tests/acceptance.py]
          volumeMounts:
            - {name: tests, mountPath: /tests, readOnly: true}
            - {name: state, mountPath: /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/.secret_key_store, subPath: store}
            - {name: state, mountPath: /var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard/local/_var_lib_openstack_lib_python3.12_site-packages_openstack_dashboard_local_.secret_key_store.lock, subPath: store.lock}
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}, runAsNonRoot: true, runAsUser: 65534, seccompProfile: {type: RuntimeDefault}}
      volumes:
        - {name: tests, configMap: {name: horizon-cost-acceptance}}
        - {name: state, emptyDir: {}}
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
