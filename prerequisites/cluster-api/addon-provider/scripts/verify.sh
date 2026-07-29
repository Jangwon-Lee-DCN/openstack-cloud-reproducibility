#!/usr/bin/env bash
set -euo pipefail

kubectl -n capi-addon-system rollout status \
  deployment/capi-addons-cluster-api-addon-provider \
  --timeout=5m

kubectl get crd helmreleases.addons.stackhpc.com
kubectl get crd manifests.addons.stackhpc.com

