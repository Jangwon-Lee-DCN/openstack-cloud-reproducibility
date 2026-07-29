#!/usr/bin/env bash
set -euo pipefail

repro_root="${REPRO_ROOT:-/home/ubuntu/openstack-cloud-reproducibility}"
chart="${ADDON_PROVIDER_CHART:-${repro_root}/helm/packages/upstream/cluster-api-addon-provider-0.12.1.tgz}"

test -f "${chart}"

helm upgrade --install capi-addons "${chart}" \
  --namespace capi-addon-system \
  --create-namespace \
  --wait \
  --timeout 10m

"$(dirname "${BASH_SOURCE[0]}")/verify.sh"

