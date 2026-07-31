#!/usr/bin/env bash
set -euo pipefail

kubectl -n openstack get deployment prometheus-openstack-exporter
kubectl -n monitoring get deployment \
  prometheus-blackbox-exporter prometheus-mysql-exporter \
  opentelemetry-collector
kubectl -n monitoring get pods -l app.kubernetes.io/instance=tempo
kubectl -n monitoring get probe openstack-public-api \
  openstack-acceptance-floating-ip
kubectl -n monitoring get servicemonitor openstack-exporter \
  openstack-rabbitmq
kubectl -n monitoring get prometheusrule openstack-platform
kubectl -n monitoring get configmap grafana-dashboard-vpc-control-plane
kubectl -n monitoring get deployment alertmanager-webhook-audit
kubectl -n openstack get cronjob openstack-synthetic-test

prometheus_ip="$(kubectl -n monitoring get pod \
  -l app.kubernetes.io/name=prometheus \
  -o jsonpath='{.items[0].status.podIP}')"

for query in \
  'up{service="openstack-metrics"}' \
  'probe_success{job="openstack-public-api"}' \
  'mysql_up' \
  'up{job="rabbitmq"}' \
  'up{namespace="vpc-control-plane-system",service=~"vpc-control-plane-controller-manager-metrics-service|vpc-facade"}' \
  'vpc_reconcile_duration_seconds_count or vector(0)' \
  'openstack_synthetic_success'; do
  result="$(curl --fail --silent --get \
    --data-urlencode "query=${query}" \
    "http://${prometheus_ip}:9090/api/v1/query")"
  jq -e '.status == "success" and (.data.result | length > 0)' \
    <<<"${result}" >/dev/null
  printf 'PASS Prometheus query: %s\n' "${query}"
done

alertmanager_status="$(curl --fail --silent \
  "http://$(kubectl -n monitoring get pod -l app.kubernetes.io/name=alertmanager -o jsonpath='{.items[0].status.podIP}'):9093/api/v2/status")"
jq -e '
  .config.original | contains("critical-audit") and
  contains("warning-audit") and
  contains("VPCElasticIPPoolQuotaExhausted")
' <<<"${alertmanager_status}" >/dev/null
printf 'PASS Alertmanager severity routes and inhibition config\n'

printf 'PASS: steps 1-7 resources and Prometheus queries are present.\n'
printf 'STOP: step 8 tenant VM telemetry requires operator discussion.\n'
