#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}
BUILD_IMAGES=${BUILD_IMAGES:-0}
VERIFY_AFTER_RECONCILE=${VERIFY_AFTER_RECONCILE:-1}
START_AT=${START_AT:-mariadb}
ONLY_RELEASE=${ONLY_RELEASE:-}
DCN_BAREMETAL_ADMIN_PROJECT_ID=${DCN_BAREMETAL_ADMIN_PROJECT_ID:-29789b94354b470f9a92d3069a114a57}
BAREMETAL_ACCESS_API_URL=${BAREMETAL_ACCESS_API_URL:-http://baremetal-access.netbox-ironic-controller.svc.cluster.local:8080}
FLAVOR_CATALOG_API_URL=${FLAVOR_CATALOG_API_URL:-http://flavor-catalog.openstack.svc.cluster.local:8080}
HORIZON_IMAGE_OVERRIDE=${HORIZON_IMAGE_OVERRIDE:-}
HORIZON_ROLLBACK_IMAGE=registry.dcn.ssu.ac.kr/openstack/horizon:source-3b143ede50340f105785@sha256:4a763abde9c848fe1c2253acc32efeec0526011627e95e029363921cf4c6264a
LOCK_FILE="$REPO_ROOT/release-lock.yaml"

if [[ -n "$HORIZON_IMAGE_OVERRIDE" && "$HORIZON_IMAGE_OVERRIDE" != "$HORIZON_ROLLBACK_IMAGE" ]]; then
  echo "Horizon override is restricted to the production-approved rollback digest" >&2
  exit 2
fi

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
  # Helm hook Jobs are unowned. Exclude CronJob-owned execution history:
  # a retained failed audit/cleaner run must not block a later healthy Helm
  # reconciliation for the entire release_group.
  while read -r obj; do
    [[ -n "$obj" ]] || continue
    kubectl wait -n "$NAMESPACE" --for=condition=complete "$obj" --timeout=15m
  done < <(
    kubectl get jobs -n "$NAMESPACE" -l "release_group=$release" -o json \
      | python3 -c '
import json, sys
for item in json.load(sys.stdin).get("items", []):
    owners = item.get("metadata", {}).get("ownerReferences", []) or []
    if not any(owner.get("kind") == "CronJob" for owner in owners):
        print("job/" + item["metadata"]["name"])
'
  )
  for kind in deployment statefulset daemonset; do
    while read -r obj; do
      [[ -n "$obj" ]] || continue
      kubectl rollout status -n "$NAMESPACE" "$obj" --timeout=15m
    done < <(kubectl get "$kind" -n "$NAMESPACE"       -l "release_group=$release" -o name 2>/dev/null || true)
  done
}

install_release() {
  local nova_cell_setup_active
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
  if [[ "$1" == "nova" ]] && kubectl -n "$NAMESPACE" get job nova-cell-setup >/dev/null 2>&1; then
    # The Nova chart retains cell-setup as a normal Job rather than a Helm
    # hook. Any rendered pod-template change is immutable, so an otherwise
    # idempotent upgrade cannot patch the completed Job. Never interrupt an
    # active setup run; replace only terminal history while the reconciler's
    # cluster-wide deployment lock is held.
    nova_cell_setup_active=$(kubectl -n "$NAMESPACE" get job nova-cell-setup \
      -o jsonpath='{.status.active}')
    if [[ "${nova_cell_setup_active:-0}" != "0" ]]; then
      echo "nova-cell-setup is active; refusing to replace it" >&2
      exit 1
    fi
    kubectl delete job -n "$NAMESPACE" nova-cell-setup --wait=true
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
    sops -d "$REPO_ROOT/$snapshot" |
      "$REPO_ROOT/deploy/scripts/render-region-values.py" >"$values"
    value_args+=( -f "$values" )
  else
    [[ -n "$values_file" && -n "$secrets_file" ]] || {
      echo "$release has neither a values snapshot nor a site/secret pair" >&2
      exit 1
    }
    values="$WORK_DIR/$release.secrets.yaml"
    sops -d "$REPO_ROOT/$secrets_file" |
      "$REPO_ROOT/deploy/scripts/render-region-values.py" >"$values"
    value_args+=( -f "$REPO_ROOT/$values_file" -f "$values" )
  fi
  # An unencrypted site file is always the final non-secret override. This
  # lets production replace old PoC storage choices retained in SOPS locks.
  if [[ -f "$REPO_ROOT/deploy/values/site/$release.yaml" && "$values_file" != "deploy/values/site/$release.yaml" ]]; then
    value_args+=( -f "$REPO_ROOT/deploy/values/site/$release.yaml" )
  fi
  if [[ "$release" == neutron ]] && kubectl -n openstack get deployment vpc-metadata-attestor >/dev/null 2>&1; then
    value_args+=( -f "$REPO_ROOT/deploy/values/features/neutron-vpc-identity.yaml" )
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
  if [[ "$release" == "horizon" && -n "$HORIZON_IMAGE_OVERRIDE" ]]; then
    value_args+=( --set-string "images.tags.horizon=$HORIZON_IMAGE_OVERRIDE" )
  fi
  helm upgrade --install "$release" "$REPO_ROOT/$package" \
    --namespace "$NAMESPACE" --create-namespace "${value_args[@]}" --timeout 15m
  if [[ "$release" == "horizon" ]]; then
    : "${DCN_BAREMETAL_ADMIN_PROJECT_ID:?exact DCN project UUID is required for Horizon}"
    : "${BAREMETAL_ACCESS_API_URL:?Bare Metal Access API URL is required for Horizon}"
    : "${FLAVOR_CATALOG_API_URL:?Flavor Catalog API URL is required for Horizon}"
    kubectl -n "$NAMESPACE" set env deployment/horizon \
      "DCN_BAREMETAL_ADMIN_PROJECT_ID=$DCN_BAREMETAL_ADMIN_PROJECT_ID" \
      "BAREMETAL_ACCESS_API_URL=$BAREMETAL_ACCESS_API_URL" \
      "FLAVOR_CATALOG_API_URL=$FLAVOR_CATALOG_API_URL"
  fi
  # Helm renders the Fernet repository as a read-only Secret volume. Restore
  # the permission-safe emptyDir + sync sidecar before waiting for Keystone's
  # rollout, otherwise its init container cannot chmod the Secret mount.
  if [[ "$release" == "keystone" ]]; then
    "$REPO_ROOT/deploy/scripts/fix-keystone-fernet-permissions.sh"
  fi
  wait_release "$release"
}

WORK_DIR=$(mktemp -d /tmp/openstack-full-reconcile.XXXXXX)
DEPLOY_LOCK=dcn-production-deploy-lock
DEPLOY_HOLDER="$(hostname)-$$-$(date +%s)"
cleanup() {
  if [[ "$(kubectl -n "$NAMESPACE" get configmap "$DEPLOY_LOCK" \
      -o jsonpath='{.data.holder}' 2>/dev/null || true)" == "$DEPLOY_HOLDER" ]]; then
    kubectl -n "$NAMESPACE" delete configmap "$DEPLOY_LOCK" \
      --ignore-not-found --wait=false >/dev/null
  fi
  shred -u "$WORK_DIR"/*.yaml 2>/dev/null || true
  rmdir "$WORK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

if ! kubectl -n "$NAMESPACE" create configmap "$DEPLOY_LOCK" \
    --from-literal="holder=$DEPLOY_HOLDER" \
    --from-literal="release=${ONLY_RELEASE:-full-stack}" >/dev/null; then
  echo "another production reconciliation owns $NAMESPACE/$DEPLOY_LOCK" >&2
  kubectl -n "$NAMESPACE" get configmap "$DEPLOY_LOCK" \
    -o jsonpath='holder={.data.holder} release={.data.release}{"\n"}' >&2 || true
  exit 1
fi

validate_admin_passwords

if [[ -z "$ONLY_RELEASE" ]]; then
  "$REPO_ROOT/deploy/scripts/install-local-path-storage.sh"
fi

if [[ "$BUILD_IMAGES" == "1" ]]; then
  "$REPO_ROOT/deploy/scripts/build-images.sh"
fi

if [[ -n "$ONLY_RELEASE" ]]; then
  if [[ "$ONLY_RELEASE" == "horizon" ]]; then
    kubectl apply -f "$REPO_ROOT/deploy/manifests/horizon-image-admission-lock.yaml"
  fi
  install_release "$ONLY_RELEASE"
  if [[ "$VERIFY_AFTER_RECONCILE" == "1" ]]; then
    case "$ONLY_RELEASE" in
      horizon) "$REPO_ROOT/deploy/scripts/verify-horizon-qoe.sh" ;;
    esac
  fi
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

"$REPO_ROOT/deploy/scripts/reconcile-rgw-keystone-catalog.sh"

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
"$REPO_ROOT/deploy/scripts/reconcile-project-facade-keystone.sh"

# OpenStack-Helm charts may recreate endpoints while releases converge. Make
# the single production region authoritative only after every service has
# registered its catalog entries, then retire the historical endpoint sets.
"$REPO_ROOT/deploy/scripts/reconcile-keystone-region.sh"

"$REPO_ROOT/deploy/scripts/verify-barbican.sh"
if [[ "$VERIFY_AFTER_RECONCILE" == "1" ]]; then
  "$REPO_ROOT/deploy/scripts/verify-full-stack.sh"
fi
