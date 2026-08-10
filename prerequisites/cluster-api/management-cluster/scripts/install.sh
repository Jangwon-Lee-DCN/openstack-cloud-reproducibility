#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

kubectl -n cert-manager wait --for=condition=Available deployment/cert-manager --timeout=5m
kubectl create namespace capo-system --dry-run=client -o yaml | kubectl apply -f -
kubectl -n harbor get secret harbor-admin-password \
  -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d |
  python3 -c 'import base64,json,sys; password=sys.stdin.read(); auth=base64.b64encode(("admin:"+password).encode()).decode(); print(json.dumps({"auths":{"registry.dcn.ssu.ac.kr":{"username":"admin","password":password,"auth":auth}}}))' |
  kubectl -n openstack create secret generic telemetry-harbor-push \
    --type=kubernetes.io/dockerconfigjson \
    --from-file=.dockerconfigjson=/dev/stdin --dry-run=client -o json |
  kubectl apply -f -
kubectl -n openstack get secret telemetry-harbor-push -o json |
  jq '.metadata={name:"harbor-registry-pull",namespace:"capo-system"} |
      del(.status)' |
  kubectl apply -f -
kubectl apply -f "${ROOT}/manifests/capo-image-build.yaml"
kubectl -n openstack wait --for=condition=complete job/capo-image-build --timeout=20m
python3 "${ROOT}/scripts/render.py" |
  kubectl apply --server-side --force-conflicts -f -
"${ROOT}/scripts/verify.sh"
