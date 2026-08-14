#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SNAPSHOT="${ROOT_DIR}/deploy/releases/octavia.values.sops.yaml"
SERVICE_PROJECT_VALUES="${ROOT_DIR}/deploy/values/site/octavia-service-project.yaml"
SITE_VALUES="${ROOT_DIR}/deploy/values/site/octavia.yaml"
PACKAGE="${ROOT_DIR}/helm/packages/patched/octavia-2026.1.0.tgz"
EXPECTED_SHA256=b8706b610be4300c8b828953885a1c9e63b845b99cf433ad546a8d02a3d9c95d
AMPHORA_CERTS="${ROOT_DIR}/deploy/secrets/octavia-amphora-certs.secret.sops.yaml"
JOBBOARD_INSTALL="${ROOT_DIR}/prerequisites/octavia-jobboard/scripts/install.sh"

endpoint_remotes() {
  local service=$1
  local port=$2
  kubectl -n openstack get endpointslice \
    -l "kubernetes.io/service-name=${service}" \
    -o jsonpath='{range .items[*].endpoints[*]}{.addresses[0]}{"\n"}{end}' |
    awk -v port="${port}" 'NF && !seen[$0]++ {printf "%stcp:%s:%s", sep, $0, port; sep=","}'
}

nb_remotes=$(endpoint_remotes ovn-ovsdb-nb 6641)
sb_remotes=$(endpoint_remotes ovn-ovsdb-sb 6642)
test -n "${nb_remotes}" && test -n "${sb_remotes}"

"${JOBBOARD_INSTALL}"

# Octavia talks to the TLS internal service catalog. Reconcile that gateway
# before copying its CA into the OpenStack namespace.
"${ROOT_DIR}/prerequisites/networking/openstack-internal-gateway/scripts/install.sh"

sops -d "${AMPHORA_CERTS}" | kubectl apply -f -
kubectl -n openstack-internal-gateway-system get secret \
  openstack-internal-ca -o json |
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"apiVersion":"v1","kind":"Secret","metadata":{"name":"openstack-internal-ca","namespace":"openstack"},"type":"Opaque","data":{"ca.crt":d["data"]["ca.crt"]}}))' |
  kubectl apply -f -

secret_values=$(mktemp /tmp/octavia-values.XXXXXX.yaml)
runtime_values=$(mktemp /tmp/octavia-runtime-values.XXXXXX.yaml)
trap 'shred -u "${secret_values}" "${runtime_values}"' EXIT
chmod 0600 "${secret_values}"
sops -d "${SNAPSHOT}" |
  "${ROOT_DIR}/deploy/scripts/render-region-values.py" >"${secret_values}"
"${ROOT_DIR}/deploy/scripts/generate-database-admin-override.py" \
  octavia "${runtime_values}"

python3 - "${runtime_values}" "${OCTAVIA_DRIVER_AGENT_REPLICAS:-6}" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
replicas = int(sys.argv[2])
if replicas < 3:
    raise SystemExit("OCTAVIA_DRIVER_AGENT_REPLICAS must be at least 3")
values = yaml.safe_load(path.read_text()) or {}
values.setdefault("pod", {}).setdefault("replicas", {})["driver_agent"] = replicas
path.write_text(yaml.safe_dump(values, sort_keys=False))
PY

python3 - "${secret_values}" "${nb_remotes}" "${sb_remotes}" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
values = yaml.safe_load(path.read_text())
values["conf"]["octavia"]["ovn"]["ovn_nb_connection"] = sys.argv[2]
values["conf"]["octavia"]["ovn"]["ovn_sb_connection"] = sys.argv[3]
path.write_text(yaml.safe_dump(values, sort_keys=False))
PY

actual_sha256=$(sha256sum "${PACKAGE}" | awk '{print $1}')
test "${actual_sha256}" = "${EXPECTED_SHA256}"

helm upgrade --install octavia "${PACKAGE}" \
  --namespace openstack \
  -f "${secret_values}" \
  -f "${SITE_VALUES}" \
  -f "${SERVICE_PROJECT_VALUES}" \
  -f "${runtime_values}" \
  --no-hooks \
  --timeout 10m

# Helm may still be finishing cleanup of hook objects from a previously
# interrupted revision when the command returns.
sleep 5

# The chart marks bootstrap jobs as post-install/post-upgrade hooks while the
# service Pods declare those same jobs as init dependencies. Running Helm with
# --wait would therefore deadlock. Render and execute the hooks explicitly in
# dependency order, then wait for the long-running workloads.
for item in \
  job-db-init.yaml:octavia-db-init \
  job-db-sync.yaml:octavia-db-sync \
  job-rabbit-init.yaml:octavia-rabbit-init \
  job-ks-service.yaml:octavia-ks-service \
  job-ks-user.yaml:octavia-ks-user \
  job-ks-endpoint.yaml:octavia-ks-endpoints \
  job-bootstrap.yaml:octavia-bootstrap; do
  template=${item%%:*}
  job=${item##*:}
  kubectl -n openstack delete job "${job}" --ignore-not-found \
    --wait=true --timeout=2m
  while kubectl -n openstack get job "${job}" >/dev/null 2>&1; do
    sleep 1
  done
  helm template octavia "${PACKAGE}" \
    --namespace openstack \
    -f "${secret_values}" \
    -f "${SITE_VALUES}" \
    -f "${SERVICE_PROJECT_VALUES}" \
    -f "${runtime_values}" \
    --show-only "templates/${template}" |
    sed '/helm.sh\/hook:/d; /helm.sh\/hook-weight:/d' |
    kubectl -n openstack apply -f -
  kubectl -n openstack wait --for=condition=complete \
    "job/${job}" --timeout=10m
done

for workload in \
  deployment/octavia-driver-agent \
  deployment/octavia-housekeeping \
  daemonset/octavia-health-manager-default \
  daemonset/octavia-worker-default \
  deployment/octavia-api; do
  kubectl -n openstack get "${workload}" >/dev/null 2>&1 || continue
  kubectl -n openstack rollout restart "${workload}"
  kubectl -n openstack rollout status "${workload}" --timeout=10m
done

kubectl -n openstack get pods -l application=octavia -o wide
