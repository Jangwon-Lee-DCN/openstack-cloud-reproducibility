#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
BUILD_IMAGES=${BUILD_IMAGES:-0}

for command in kubectl helm sops; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

if [[ "$BUILD_IMAGES" == "1" ]]; then
  "$REPO_ROOT/deploy/scripts/build-images.sh"
fi

# Environment-profile secrets. Replace/re-encrypt them for a different cloud.
for secret in telemetry-harbor-push.secret.sops.yaml               gnocchi-runtime.secret.sops.yaml               gnocchi-config.secret.sops.yaml; do
  sops -d "$REPO_ROOT/deploy/secrets/$secret" | kubectl apply -f -
done

kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi-bucket.yaml"
kubectl wait -n "$NAMESPACE" --for=jsonpath='{.status.phase}'=Bound   objectbucketclaim/gnocchi-metrics --timeout=10m

# Gnocchi creates several RGW buckets. Rook OBC users often default to one.
if kubectl get deployment -n rook-ceph rook-ceph-tools >/dev/null 2>&1; then
  access_key=$(kubectl get secret -n "$NAMESPACE" gnocchi-metrics     -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d)
  kubectl exec -n rook-ceph deployment/rook-ceph-tools --     radosgw-admin user modify --access-key="$access_key" --max-buckets=10 >/dev/null
fi

kubectl delete job -n "$NAMESPACE" gnocchi-keystone-bootstrap --ignore-not-found
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi-keystone-bootstrap.yaml"
kubectl wait -n "$NAMESPACE" --for=condition=complete   job/gnocchi-keystone-bootstrap --timeout=10m
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi.yaml"
kubectl rollout status -n "$NAMESPACE" deployment/gnocchi-api --timeout=10m
kubectl rollout status -n "$NAMESPACE" deployment/gnocchi-metricd --timeout=10m

work_dir=$(mktemp -d /tmp/openstack-telemetry-reconcile.XXXXXX)
cleanup() {
  shred -u "$work_dir"/*.yaml 2>/dev/null || true
  rmdir "$work_dir" 2>/dev/null || true
}
trap cleanup EXIT

sops -d "$REPO_ROOT/deploy/secrets/ceilometer.values.sops.yaml"   > "$work_dir/ceilometer.yaml"
kubectl delete job -n "$NAMESPACE" ceilometer-db-sync --ignore-not-found
helm upgrade --install ceilometer "$REPO_ROOT/helm/openstack-helm/ceilometer"   --namespace "$NAMESPACE"   -f "$REPO_ROOT/deploy/values/site/ceilometer.yaml"   -f "$work_dir/ceilometer.yaml" --timeout 15m --wait
kubectl apply -f "$REPO_ROOT/deploy/manifests/ceilometer-pdb.yaml"

sops -d "$REPO_ROOT/deploy/secrets/aodh.values.sops.yaml"   > "$work_dir/aodh.yaml"
kubectl delete job -n "$NAMESPACE" aodh-db-sync --ignore-not-found
helm upgrade --install aodh "$REPO_ROOT/helm/openstack-helm/aodh"   --namespace "$NAMESPACE"   -f "$REPO_ROOT/deploy/values/site/aodh.yaml"   -f "$work_dir/aodh.yaml" --timeout 15m --wait

kubectl apply -f "$REPO_ROOT/deploy/manifests/openstack-public-routes.yaml"
"$REPO_ROOT/deploy/scripts/verify.sh"
