#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHART="${ROOT_DIR}/charts/valkey-6.2.4.tgz"
VALUES="${ROOT_DIR}/values/valkey.yaml"
SECRET="${ROOT_DIR}/secrets/octavia-valkey-auth.secret.sops.yaml"
EXPECTED_SHA256=3bb94150e9bd16c17b55c2706a5284d03e0e8c61d66893d1682a9aa77300b69b

test "$(sha256sum "${CHART}" | awk '{print $1}')" = "${EXPECTED_SHA256}"
sops -d "${SECRET}" | kubectl apply -f -

helm upgrade --install octavia-valkey "${CHART}" \
  --namespace openstack \
  --create-namespace \
  -f "${VALUES}" \
  --wait \
  --timeout 10m

"${ROOT_DIR}/scripts/verify.sh"
