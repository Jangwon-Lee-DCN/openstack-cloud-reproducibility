#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
REPRO=${REPRO_ROOT:-$(CDPATH= cd -- "$ROOT/.." && pwd)}
RUNTIME_VALUES=$(mktemp /tmp/designate-runtime-values.XXXXXX.yaml)
cleanup() {
  shred -u "$RUNTIME_VALUES" 2>/dev/null || true
}
trap cleanup EXIT
"$ROOT/scripts/generate-database-admin-override.py" designate "$RUNTIME_VALUES"

for file in \
  "$ROOT/secrets/powerdns.values.sops.yaml" \
  "$ROOT/secrets/designate.values.sops.yaml"; do
  test -f "$file" || {
    echo "missing encrypted values: $file" >&2
    exit 1
  }
done

helm upgrade --install powerdns \
  "$REPRO/helm/packages/patched/powerdns-2026.1.0.tgz" \
  --namespace openstack \
  --timeout 15m \
  -f "$ROOT/releases/powerdns.site.yaml" \
  -f <(sops -d "$ROOT/secrets/powerdns.values.sops.yaml") \
  -f "$RUNTIME_VALUES"

kubectl delete job powerdns-schema-4-9 --namespace openstack \
  --ignore-not-found
kubectl apply -f "$ROOT/manifests/powerdns-schema-4.9-migration.yaml"
kubectl wait --namespace openstack --for=condition=complete \
  job/powerdns-schema-4-9 --timeout=5m
kubectl rollout restart deployment/powerdns --namespace openstack
kubectl rollout status deployment/powerdns --namespace openstack --timeout=5m

kubectl apply -f "$ROOT/manifests/designate-authoritative-dns.yaml"

helm upgrade --install designate \
  "$REPRO/helm/packages/patched/designate-2026.1.0.tgz" \
  --namespace openstack \
  --timeout 20m \
  --wait \
  -f "$ROOT/releases/designate.site.yaml" \
  -f <(sops -d "$ROOT/secrets/designate.values.sops.yaml") \
  -f "$RUNTIME_VALUES"

# Reconcile the database-backed pool definition on upgrades as well as fresh
# installs, then restart workers so their lazy pool cache cannot retain an old
# DNS target or mDNS primary address.
kubectl exec --namespace openstack deployment/designate-central \
  --container designate-central -- designate-manage pool update
kubectl rollout restart deployment/designate-worker --namespace openstack
kubectl rollout status deployment/designate-worker \
  --namespace openstack --timeout=5m

kubectl apply -f "$ROOT/manifests/designate-public-route.yaml"
