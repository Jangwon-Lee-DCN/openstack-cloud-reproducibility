#!/usr/bin/env bash
set -euo pipefail

readonly namespace=monitoring
readonly rule=alert-delivery-e2e
cleanup() {
  kubectl -n "${namespace}" delete prometheusrule "${rule}" --ignore-not-found >/dev/null
}
trap cleanup EXIT

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
kubectl apply -f - <<'EOF'
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: alert-delivery-e2e
  namespace: monitoring
spec:
  groups:
    - name: alert-delivery.e2e
      rules:
        - alert: AlertDeliveryE2EWarning
          expr: vector(1)
          labels: {severity: warning}
          annotations:
            summary: Local-only Alertmanager delivery test
            runbook_url: https://github.com/Jangwon-Lee-DCN/openstack-cloud-reproducibility/blob/main/deploy/monitoring/docs/alert-delivery.md#delivery-test
EOF

for _ in $(seq 1 90); do
  if kubectl -n "${namespace}" logs deployment/alertmanager-webhook-audit --since-time="${started_at}" 2>/dev/null | grep -q 'POST /test'; then
    printf 'PASS: Prometheus -> Alertmanager test route -> local audit webhook\n'
    exit 0
  fi
  sleep 2
done

printf 'FAIL: test alert was not delivered to the local warning receiver\n' >&2
exit 1
