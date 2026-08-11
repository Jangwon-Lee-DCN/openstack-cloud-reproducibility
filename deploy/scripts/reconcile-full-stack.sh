#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
BUILD_IMAGES=${BUILD_IMAGES:-0}
VERIFY_AFTER_RECONCILE=${VERIFY_AFTER_RECONCILE:-1}
START_AT=${START_AT:-mariadb}
ONLY_RELEASE=${ONLY_RELEASE:-}
LOCK_FILE="$REPO_ROOT/release-lock.yaml"

for command in kubectl helm sops python3 sha256sum curl; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done

release_field() {
  local release=$1 field=$2
  python3 - "$LOCK_FILE" "$release" "$field" <<'PYLOCK'
import sys,yaml
lock,name,field=sys.argv[1:]
d=yaml.safe_load(open(lock))
x=next(x for x in d['spec']['releases'] if x['name']==name)
print(x.get(field, ''))
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
    snapshot = release.get("valuesSnapshot") or release.get("secretsFile")
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
  if [[ "$1" == "designate" ]]; then
    "$REPO_ROOT/deploy/scripts/install-designate.sh"
    return
  fi
  if [[ "$1" == "magnum" ]]; then
    "$REPO_ROOT/deploy/scripts/install-magnum.sh"
    return
  fi
  if [[ "$1" == "neutron" ]]; then
    sops -d "$REPO_ROOT/deploy/secrets/telemetry-harbor-push.secret.sops.yaml" \
      | kubectl apply -f -
    kubectl apply \
      -f "$REPO_ROOT/deploy/manifests/neutron-harbor-serviceaccounts.yaml"
  fi
  if [[ "$1" == "prometheus-openstack-exporter" ]]; then
    # This chart manages its bootstrap Job as a normal resource. Pod-template
    # scheduling changes are immutable, so remove only the completed/pending
    # bootstrap Job before the idempotent Helm upgrade recreates it.
    kubectl delete job -n "$NAMESPACE" \
      prometheus-openstack-exporter-ks-user --ignore-not-found --wait=true
  fi
  local release=$1 package snapshot values_file secrets_file expected actual values
  package=$(release_field "$release" package)
  snapshot=$(release_field "$release" valuesSnapshot)
  values_file=$(release_field "$release" valuesFile)
  secrets_file=$(release_field "$release" secretsFile)
  expected=$(release_field "$release" sha256)
  actual=$(sha256sum "$REPO_ROOT/$package" | awk '{print $1}')
  [[ "$actual" == "$expected" ]] || {
    echo "$release package checksum mismatch" >&2; exit 1;
  }
  local -a value_args=()
  if [[ -n "$snapshot" ]]; then
    values="$WORK_DIR/$release.yaml"
    sops -d "$REPO_ROOT/$snapshot" > "$values"
    value_args+=( -f "$values" )
  else
    [[ -n "$values_file" && -n "$secrets_file" ]] || {
      echo "$release has neither a values snapshot nor a site/secret pair" >&2
      exit 1
    }
    values="$WORK_DIR/$release.secrets.yaml"
    sops -d "$REPO_ROOT/$secrets_file" > "$values"
    value_args+=( -f "$REPO_ROOT/$values_file" -f "$values" )
  fi
  # An unencrypted site file is always the final non-secret override. This
  # lets production replace old PoC storage choices retained in SOPS locks.
  if [[ -f "$REPO_ROOT/deploy/values/site/$release.yaml" && "$values_file" != "deploy/values/site/$release.yaml" ]]; then
    value_args+=( -f "$REPO_ROOT/deploy/values/site/$release.yaml" )
  fi
  if [[ "$release" == "cinder" || "$release" == "manila" ]]; then
    powerstore_values="$WORK_DIR/$release.powerstore.yaml"
    "$REPO_ROOT/deploy/scripts/generate-powerstore-overrides.py" "$release" "$powerstore_values"
    value_args+=( -f "$powerstore_values" )
  fi
  if [[ "$release" == "barbican" ]]; then
    barbican_kek_values="$WORK_DIR/barbican.kek.yaml"
    "$REPO_ROOT/deploy/scripts/generate-barbican-kek-override.py" "$barbican_kek_values"
    value_args+=( -f "$barbican_kek_values" )
  fi
  if [[ "$release" == "keystone" ]]; then
    oidc_values="$WORK_DIR/keystone.oidc.yaml"
    "$REPO_ROOT/deploy/scripts/generate-keycloak-oidc-override.py" "$values" "$oidc_values"
    value_args+=( -f "$oidc_values" )
  fi
  case "$release" in
    keystone|placement|glance|cinder|manila|barbican|heat|nova|masakari|neutron|octavia|magnum|designate|ceilometer|aodh)
      database_values="$WORK_DIR/$release.database-admin.yaml"
      "$REPO_ROOT/deploy/scripts/generate-database-admin-override.py" "$release" "$database_values"
      value_args+=( -f "$database_values" )
      ;;
  esac
  helm upgrade --install "$release" "$REPO_ROOT/$package" \
    --namespace "$NAMESPACE" --create-namespace "${value_args[@]}" --timeout 15m
  wait_release "$release"
}

WORK_DIR=$(mktemp -d /tmp/openstack-full-reconcile.XXXXXX)
cleanup() {
  shred -u "$WORK_DIR"/*.yaml 2>/dev/null || true
  rmdir "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

validate_admin_passwords

"$REPO_ROOT/deploy/scripts/install-local-path-storage.sh"

if [[ "$BUILD_IMAGES" == "1" ]]; then
  "$REPO_ROOT/deploy/scripts/build-images.sh"
fi

if [[ -n "$ONLY_RELEASE" ]]; then
  install_release "$ONLY_RELEASE"
  exit 0
fi

# Dependency order of the accepted deployment. START_AT allows an idempotent
# resume after a corrected release without replaying already healthy layers.
resume=0
for release in   mariadb rabbitmq memcached   keystone placement   glance cinder manila barbican   openvswitch ovn neutron designate   libvirt nova masakari   heat octavia magnum horizon skyline ironic   prometheus-openstack-exporter; do
  [[ "$release" == "$START_AT" ]] && resume=1
  [[ "$resume" == "1" ]] || continue
  install_release "$release"
done
[[ "$resume" == "1" ]] || { echo "unknown START_AT release: $START_AT" >&2; exit 2; }

# Gnocchi is intentionally manifest-managed because its upstream chart runtime
# is obsolete. Its SOPS profile is environment-specific.
for secret in telemetry-harbor-push.secret.sops.yaml gnocchi-runtime.secret.sops.yaml; do
  sops -d "$REPO_ROOT/deploy/secrets/$secret" | kubectl apply -f -
done
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi-bucket.yaml"
kubectl wait -n "$NAMESPACE" --for=jsonpath='{.status.phase}'=Bound   objectbucketclaim/gnocchi-metrics --timeout=10m
"$REPO_ROOT/deploy/scripts/reconcile-gnocchi-runtime.py"
# The OBC provisioner owns the RGW identity. Do not mutate it with
# radosgw-admin: recent Ceph account-backed users cannot be modified by access
# key alone, and Gnocchi needs only the single bucket already created above.
kubectl delete job -n "$NAMESPACE" gnocchi-keystone-bootstrap --ignore-not-found
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi-keystone-bootstrap.yaml"
kubectl wait -n "$NAMESPACE" --for=condition=complete   job/gnocchi-keystone-bootstrap --timeout=10m
kubectl delete job -n "$NAMESPACE" gnocchi-upgrade --ignore-not-found --wait=true
kubectl apply -f "$REPO_ROOT/deploy/manifests/gnocchi.yaml"
kubectl wait -n "$NAMESPACE" --for=condition=complete job/gnocchi-upgrade --timeout=10m
kubectl rollout status -n "$NAMESPACE" deployment/gnocchi-api --timeout=15m
kubectl rollout status -n "$NAMESPACE" deployment/gnocchi-metricd --timeout=15m

install_release ceilometer
kubectl apply -f "$REPO_ROOT/deploy/manifests/ceilometer-pdb.yaml"
install_release aodh
kubectl -n "$NAMESPACE" delete job telemetry-resource-type-reconcile --ignore-not-found
kubectl apply -f "$REPO_ROOT/deploy/manifests/telemetry-resource-type-reconcile.yaml"
kubectl -n "$NAMESPACE" wait --for=condition=complete \
  job/telemetry-resource-type-reconcile --timeout=10m
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
