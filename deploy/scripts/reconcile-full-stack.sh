#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
BUILD_IMAGES=${BUILD_IMAGES:-0}
VERIFY_AFTER_RECONCILE=${VERIFY_AFTER_RECONCILE:-1}
LOCK_FILE="$REPO_ROOT/release-lock.yaml"

for command in kubectl helm sops python3 sha256sum; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

release_field() {
  local release=$1 field=$2
  python3 - "$LOCK_FILE" "$release" "$field" <<'PYLOCK'
import sys,yaml
lock,name,field=sys.argv[1:]
d=yaml.safe_load(open(lock))
x=next(x for x in d['spec']['releases'] if x['name']==name)
print(x[field])
PYLOCK
}

validate_admin_passwords() {
  local canonical_digest="" digest password release snapshot

  while read -r release snapshot; do
    if ! password=$(sops -d \
      --extract '["endpoints"]["identity"]["auth"]["admin"]["password"]' \
      "$REPO_ROOT/$snapshot" 2>/dev/null); then
      continue
    fi
    digest=$(printf '%s' "$password" | sha256sum | awk '{print $1}')
    unset password
    if [[ -z "$canonical_digest" ]]; then
      canonical_digest=$digest
    elif [[ "$digest" != "$canonical_digest" ]]; then
      echo "$release has a different Keystone admin password in $snapshot" >&2
      echo "refusing reconciliation because repeated failures can lock the admin account" >&2
      exit 1
    fi
  done < <(
    python3 - "$LOCK_FILE" <<'PYLOCK'
import sys
import yaml

with open(sys.argv[1]) as stream:
    lock = yaml.safe_load(stream)
for release in lock["spec"]["releases"]:
    snapshot = release.get("valuesSnapshot")
    if snapshot:
        print(release["name"], snapshot)
PYLOCK
  )
}

wait_release() {
  local release=$1 obj
  if kubectl get jobs -n "$NAMESPACE" -l "release_group=$release" -o name | grep -q .; then
    kubectl wait -n "$NAMESPACE" --for=condition=complete       job -l "release_group=$release" --timeout=15m
  fi
  for kind in deployment statefulset daemonset; do
    while read -r obj; do
      [[ -n "$obj" ]] || continue
      kubectl rollout status -n "$NAMESPACE" "$obj" --timeout=15m
    done < <(kubectl get "$kind" -n "$NAMESPACE"       -l "release_group=$release" -o name 2>/dev/null || true)
  done
}

install_release() {
  if [[ "$1" == "octavia" ]]; then
    "$REPO_ROOT/deploy/scripts/reconcile-octavia.sh"
    return
  fi
  if [[ "$1" == "neutron" ]]; then
    sops -d "$REPO_ROOT/deploy/secrets/telemetry-harbor-push.secret.sops.yaml" \
      | kubectl apply -f -
    kubectl apply \
      -f "$REPO_ROOT/deploy/manifests/neutron-harbor-serviceaccounts.yaml"
  fi
  local release=$1 package snapshot expected actual values
  package=$(release_field "$release" package)
  snapshot=$(release_field "$release" valuesSnapshot)
  expected=$(release_field "$release" sha256)
  actual=$(sha256sum "$REPO_ROOT/$package" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || {
    echo "$release package checksum mismatch" >&2; exit 1;
  }
  values="$WORK_DIR/$release.yaml"
  sops -d "$REPO_ROOT/$snapshot" > "$values"
  helm upgrade --install "$release" "$REPO_ROOT/$package"     --namespace "$NAMESPACE" --create-namespace -f "$values" --timeout 15m
  if [[ "$release" == "horizon" ]]; then
    "$REPO_ROOT/deploy/scripts/ensure-horizon-static-ownership.sh"
  fi
  wait_release "$release"
}

WORK_DIR=$(mktemp -d /tmp/openstack-full-reconcile.XXXXXX)
cleanup() {
  shred -u "$WORK_DIR"/*.yaml 2>/dev/null || true
  rmdir "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

validate_admin_passwords

if [[ "$BUILD_IMAGES" == "1" ]]; then
  "$REPO_ROOT/deploy/scripts/build-images.sh"
fi

# Dependency order of the accepted PoC deployment.
for release in   ceph-adapter-rook   mariadb rabbitmq memcached   keystone placement   glance cinder barbican   openvswitch ovn neutron   libvirt nova   heat octavia horizon skyline ironic   prometheus-openstack-exporter; do
  install_release "$release"
done

# Gnocchi is intentionally manifest-managed because its upstream chart runtime
# is obsolete. Its SOPS profile is environment-specific.
for secret in telemetry-harbor-push.secret.sops.yaml               gnocchi-runtime.secret.sops.yaml               gnocchi-config.secret.sops.yaml; do
  sops -d "$REPO_ROOT/deploy/secrets/$secret" | kubectl apply -f -
done
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi-bucket.yaml"
kubectl wait -n "$NAMESPACE" --for=jsonpath='{.status.phase}'=Bound   objectbucketclaim/gnocchi-metrics --timeout=10m
if kubectl get deployment -n rook-ceph rook-ceph-tools >/dev/null 2>&1; then
  access_key=$(kubectl get secret -n "$NAMESPACE" gnocchi-metrics     -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d)
  kubectl exec -n rook-ceph deployment/rook-ceph-tools --     radosgw-admin user modify --access-key="$access_key" --max-buckets=10 >/dev/null
fi
kubectl delete job -n "$NAMESPACE" gnocchi-keystone-bootstrap --ignore-not-found
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi-keystone-bootstrap.yaml"
kubectl wait -n "$NAMESPACE" --for=condition=complete   job/gnocchi-keystone-bootstrap --timeout=10m
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi.yaml"
kubectl rollout status -n "$NAMESPACE" deployment/gnocchi-api --timeout=15m
kubectl rollout status -n "$NAMESPACE" deployment/gnocchi-metricd --timeout=15m

install_release ceilometer
kubectl apply -f "$REPO_ROOT/deploy/manifests/ceilometer-pdb.yaml"
install_release aodh
kubectl apply -f "$REPO_ROOT/deploy/manifests/openstack-public-routes.yaml"
kubectl apply -f "$REPO_ROOT/deploy/manifests/keystone-oidc-federation-routes.yaml"
"$REPO_ROOT/deploy/scripts/fix-keystone-fernet-permissions.sh"

# project-facade: self-service project lifecycle API (see
# docs/proposals/iam-hardening/README.md, "New permission tier"). Its
# service credential (deploy/secrets/project-facade-keystone.secret.sops.yaml)
# and the Keystone-side project-creator role/group
# (deploy/scripts/reconcile-iam-dcn.sh) are provisioned separately, not
# here -- this only applies the already-built API service itself.
sops -d "$REPO_ROOT/deploy/secrets/project-facade-keystone.secret.sops.yaml" | kubectl apply -f -
kubectl apply -f "$REPO_ROOT/deploy/manifests/project-facade.yaml"
kubectl apply -f "$REPO_ROOT/deploy/manifests/project-facade-routes.yaml"
kubectl -n openstack rollout status deployment/project-facade --timeout=5m

"$REPO_ROOT/deploy/scripts/verify-barbican.sh"
if [[ "$VERIFY_AFTER_RECONCILE" == "1" ]]; then
  "$REPO_ROOT/deploy/scripts/verify-full-stack.sh"
fi
