#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
deployment_dir="$(cd -- "${script_dir}/../.." && pwd)"
manifest="${deployment_dir}/manifests/magnum-image-build.yaml"

kubectl -n openstack create configmap magnum-capi-image-build \
  --from-file=Dockerfile="${script_dir}/Dockerfile" \
  --from-file=patch_token_file.py="${script_dir}/patch_token_file.py" \
  --dry-run=client -o yaml |
  kubectl apply -f -

kubectl -n openstack delete job magnum-capi-image-build \
  --ignore-not-found --wait=true
kubectl apply -f "${manifest}"
kubectl -n openstack wait \
  --for=condition=complete job/magnum-capi-image-build \
  --timeout=30m

kubectl -n openstack get pod \
  -l job-name=magnum-capi-image-build \
  -o jsonpath='{.items[0].status.containerStatuses[0].state.terminated.message}{"\n"}'
