#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work=$(mktemp -d /tmp/keystone-oidc.XXXXXX)
cleanup() { shred -u "$work"/*.yaml 2>/dev/null || true; rmdir "$work" 2>/dev/null || true; }
trap cleanup EXIT

readarray -t fields < <(python3 - "$ROOT/release-lock.yaml" <<'PY'
import sys,yaml
d=yaml.safe_load(open(sys.argv[1]))
r=next(x for x in d['spec']['releases'] if x['name']=='keystone')
print(r['package']); print(r['sha256']); print(r['valuesSnapshot'])
PY
)
package=${fields[0]}; expected=${fields[1]}; snapshot=${fields[2]}
test "$(sha256sum "$ROOT/$package" | awk '{print $1}')" = "$expected"
sops -d "$ROOT/$snapshot" > "$work/base.yaml"
"$ROOT/deploy/scripts/generate-keycloak-oidc-override.py" "$work/base.yaml" "$work/oidc.yaml"
"$ROOT/deploy/scripts/generate-database-admin-override.py" keystone "$work/database.yaml"
"$ROOT/deploy/scripts/sync-internal-ca.sh"
"$ROOT/deploy/scripts/fix-keystone-fernet-permissions.sh" --restore-chart-state
helm upgrade --install keystone "$ROOT/$package" -n openstack \
  -f "$work/base.yaml" -f "$ROOT/deploy/values/site/keystone.yaml" \
  -f "$work/oidc.yaml" -f "$work/database.yaml" --timeout 15m
kubectl -n openstack wait --for=condition=complete job -l release_group=keystone --timeout=15m
"$ROOT/deploy/scripts/fix-keystone-fernet-permissions.sh"
kubectl -n openstack rollout status deployment/keystone-api --timeout=15m
if kubectl -n openstack get secret keystone-etc -o jsonpath='{.data.wsgi-keystone\.conf}' |
  base64 -d | grep -q 'OIDCClientSecret "replace-me"'; then
  echo "Keystone OIDC client secret is still a placeholder" >&2
  exit 1
fi
echo "Keystone OIDC configuration reconciled without placeholder credentials."
