#!/usr/bin/env bash
set -euo pipefail

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT="$(cd "${ROOT}/../../.." && pwd)"

for command_name in kubectl helm sops jq curl; do
  command -v "${command_name}" >/dev/null
done

kubectl apply -f "${ROOT}/manifests/alertmanager-webhook-audit.yaml"
kubectl -n monitoring rollout status deployment/alertmanager-webhook-audit \
  --timeout=300s

# Preserve the existing kube-prometheus-stack installation and change only
# Alertmanager routing. External Slack/SMTP receivers are intentionally not
# configured; see docs/alert-delivery.md.
helm upgrade kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack --version 87.18.1 \
  -n monitoring --reuse-values \
  -f "${ROOT}/values/alertmanager-routing.yaml" \
  --wait --timeout 10m

# Restore Git-safe credentials before chart reconciliation.
sops --decrypt "${ROOT}/secrets/mariadb-exporter.secret.sops.yaml" |
  kubectl apply -f -
sops --decrypt "${ROOT}/secrets/openstack-exporter.secret.sops.yaml" |
  kubectl apply -f -

admin_password="$(kubectl -n openstack get secret keystone-keystone-admin \
  -o jsonpath='{.data.OS_PASSWORD}' | base64 -d)"
exporter_password="$(kubectl -n openstack get secret \
  prometheus-openstack-exporter-keystone-user \
  -o jsonpath='{.data.OS_PASSWORD}' | base64 -d)"

helm upgrade --install prometheus-openstack-exporter \
  "${REPO_ROOT}/helm/packages/upstream/prometheus-openstack-exporter-2026.1.0.tgz" \
  -n openstack -f "${ROOT}/values/openstack-exporter.yaml" \
  --set-string endpoints.identity.auth.admin.password="${admin_password}" \
  --set-string endpoints.identity.auth.user.password="${exporter_password}" \
  --wait=false
unset admin_password exporter_password

# This OSH chart does not expose a Deployment tolerations value.
kubectl -n openstack patch deployment prometheus-openstack-exporter \
  --type=strategic \
  -p '{"spec":{"template":{"spec":{"tolerations":[{"key":"node-role.kubernetes.io/control-plane","operator":"Exists","effect":"NoSchedule"}]}}}}'
kubectl -n openstack rollout status \
  deployment/prometheus-openstack-exporter --timeout=600s

helm upgrade --install prometheus-blackbox-exporter \
  prometheus-community/prometheus-blackbox-exporter --version 11.15.1 \
  -n monitoring -f "${ROOT}/values/blackbox.yaml" --wait --timeout 10m

mariadb_password="$(kubectl -n monitoring get secret \
  openstack-mariadb-exporter -o jsonpath='{.data.password}' | base64 -d)"
kubectl -n openstack exec mariadb-server-0 -c mariadb -- \
  mariadb --defaults-extra-file=/etc/mysql/admin_user.cnf \
  -e "CREATE USER IF NOT EXISTS 'prometheus'@'%' IDENTIFIED BY '${mariadb_password}';
      ALTER USER 'prometheus'@'%' IDENTIFIED BY '${mariadb_password}';
      GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'prometheus'@'%';
      FLUSH PRIVILEGES;"
unset mariadb_password

helm upgrade --install prometheus-mysql-exporter \
  prometheus-community/prometheus-mysql-exporter --version 2.14.0 \
  -n monitoring -f "${ROOT}/values/mysql-exporter.yaml" \
  --wait --timeout 10m

helm upgrade --install prometheus-pushgateway \
  prometheus-community/prometheus-pushgateway --version 3.7.0 \
  -n monitoring \
  --set serviceMonitor.enabled=true \
  --set persistentVolume.enabled=true \
  --set persistentVolume.storageClass=rook-ceph-block \
  --set persistentVolume.size=2Gi \
  --set nodeSelector.openstack-control-plane=enabled \
  --set 'tolerations[0].key=node-role.kubernetes.io/control-plane' \
  --set 'tolerations[0].operator=Exists' \
  --set 'tolerations[0].effect=NoSchedule' \
  --wait --timeout 10m

kubectl apply \
  -f "${ROOT}/manifests/native-service-monitors.yaml" \
  -f "${ROOT}/manifests/blackbox-probes.yaml" \
  -f "${ROOT}/manifests/dashboard.yaml" \
  -f "${ROOT}/manifests/vpc-control-plane-dashboard.yaml" \
  -f "${ROOT}/manifests/vpc-iam-audit-dashboard.yaml" \
  -f "${ROOT}/manifests/openstack-service-dashboards.yaml" \
  -f "${ROOT}/manifests/alerts.yaml" \
  -f "${ROOT}/manifests/synthetic-test.yaml" \
  -f "${ROOT}/manifests/tempo-bucket.yaml"

for _ in $(seq 1 60); do
  kubectl -n monitoring get secret tempo-traces >/dev/null 2>&1 &&
    kubectl -n monitoring get configmap tempo-traces >/dev/null 2>&1 &&
    break
  sleep 2
done

helm upgrade --install tempo grafana/tempo-distributed --version 1.61.3 \
  -n monitoring -f "${ROOT}/values/tempo-distributed.yaml" \
  --wait --timeout 20m

helm upgrade --install opentelemetry-collector \
  open-telemetry/opentelemetry-collector --version 0.165.0 \
  -n monitoring -f "${ROOT}/values/otel-collector.yaml" \
  --wait --timeout 10m

kubectl apply -f "${ROOT}/manifests/tempo-datasource.yaml"

"${ROOT}/scripts/verify.sh"
printf 'STOP: step 8 was not installed; discuss the tenant VM agent policy.\n'
