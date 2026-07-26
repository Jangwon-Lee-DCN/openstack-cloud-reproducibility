#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SNAPSHOT="${ROOT_DIR}/deploy/releases/octavia.values.sops.yaml"
PACKAGE="${ROOT_DIR}/helm/packages/patched/octavia-2026.1.0.tgz"
EXPECTED_SHA256=b3ef67f4ae2fcb53b217bf1b271ce32c31f9cda1ea33583ddd5a473e32380036
REMOTE_CONTROLLER="${REMOTE_CONTROLLER:-cloud-controller-1}"

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

sudo -n install -d -o 42424 -g 42424 -m 0750 /var/lib/octavia/run
ssh -o BatchMode=yes "${REMOTE_CONTROLLER}" \
  "sudo -n install -d -o 42424 -g 42424 -m 0750 /var/lib/octavia/run"

secret_values=$(mktemp /tmp/octavia-values.XXXXXX.yaml)
trap 'shred -u "${secret_values}"' EXIT
chmod 0600 "${secret_values}"
sops -d "${SNAPSHOT}" >"${secret_values}"

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
  --no-hooks \
  --wait \
  --timeout 10m

kubectl -n openstack get pods -l application=octavia -o wide
