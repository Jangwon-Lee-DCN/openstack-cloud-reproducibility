#!/usr/bin/env bash
set -euo pipefail

operation=${1:?deploy, verify, or rollback}
: "${DEVELOPMENT_NAMESPACE:?development wrapper must set DEVELOPMENT_NAMESPACE}"
: "${DEVELOPMENT_NAME:?development wrapper must set DEVELOPMENT_NAME}"
[[ $DEVELOPMENT_NAME == glance-image-protection ]]
[[ $DEVELOPMENT_NAMESPACE == development-glance-image-protection ]]
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
image=quay.io/airshipit/openstack-client@sha256:8a402a50ecf2afe14f580ad2bae17433605c29063b0d5e2c0f3d3c962d13c656

case "$operation" in
  deploy)
    grep -q 'image-inspector-body' "$root/images/horizon-complete/image_catalog/index_split.html"
    grep -q 'openstack_dashboard/templates/project/images/index_split.html' \
      "$root/images/horizon-complete/Dockerfile"
    grep -q 'get_template("project/images/index_split.html")' \
      "$root/deploy/scripts/verify-horizon-capabilities.sh"
    bash -n "$root/deploy/scripts/verify-glance-image-rbac.sh"
    bash -n "$root/deploy/scripts/reconcile-glance-image-freshness.sh"
    bash -n "$root/deploy/scripts/drill-glance-image-restore.sh"
    kubectl -n "$DEVELOPMENT_NAMESPACE" create configmap glance-image-protection-tests \
      --from-file=glance_image_protection.py="$root/deploy/scripts/glance_image_protection.py" \
      --from-file=test_glance_image_protection.py="$root/deploy/tests/test_glance_image_protection.py" \
      --from-file=glance_image_catalog.py="$root/deploy/scripts/glance_image_catalog.py" \
      --from-file=test_glance_image_catalog.py="$root/deploy/tests/test_glance_image_catalog.py" \
      --from-file=verify_image_supply_chain.py="$root/deploy/scripts/verify_image_supply_chain.py" \
      --from-file=test_verify_image_supply_chain.py="$root/deploy/tests/test_verify_image_supply_chain.py" \
      --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl -n "$DEVELOPMENT_NAMESPACE" delete job glance-image-protection-tests \
      --ignore-not-found --wait=true >/dev/null
    kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata: {name: glance-image-protection-tests, namespace: $DEVELOPMENT_NAMESPACE}
spec:
  backoffLimit: 0
  template:
    metadata: {labels: {app: glance-image-protection-tests}}
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      priorityClassName: dcn-development-interruptible
      nodeSelector: {dcn.ssu.ac.kr/workload-class: development}
      tolerations:
        - {key: dcn.ssu.ac.kr/workload-class, operator: Equal, value: development, effect: NoSchedule}
        - {key: node-role.kubernetes.io/utility, operator: Equal, value: "true", effect: NoSchedule}
      containers:
        - name: tests
          image: $image
          command: [sh, -lc]
          args:
            - python3 /tests/test_glance_image_protection.py -v && python3 /tests/test_glance_image_catalog.py -v && python3 /tests/test_verify_image_supply_chain.py -v
          volumeMounts: [{name: tests, mountPath: /tests, readOnly: true}]
          securityContext:
            allowPrivilegeEscalation: false
            capabilities: {drop: [ALL]}
            runAsNonRoot: true
            runAsUser: 65534
            seccompProfile: {type: RuntimeDefault}
      volumes:
        - name: tests
          configMap: {name: glance-image-protection-tests, defaultMode: 0555}
EOF
    ;;
  verify)
    kubectl -n "$DEVELOPMENT_NAMESPACE" wait --for=condition=complete \
      job/glance-image-protection-tests --timeout=5m
    kubectl -n "$DEVELOPMENT_NAMESPACE" logs job/glance-image-protection-tests | \
      grep -q '^OK$'
    ;;
  rollback)
    kubectl -n "$DEVELOPMENT_NAMESPACE" delete job glance-image-protection-tests \
      --ignore-not-found --wait=true
    ;;
  *) echo "unsupported operation: $operation" >&2; exit 2 ;;
esac
