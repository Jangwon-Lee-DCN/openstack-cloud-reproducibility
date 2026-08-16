#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
namespace=openstack
release=cloudkitty
package="$root/helm/packages/patched/cloudkitty-2026.1.0.tgz"
values="$root/deploy/values/site/cloudkitty.yaml"
secrets="$root/deploy/secrets/cloudkitty.values.sops.yaml"
route="$root/deploy/manifests/cloudkitty-public-route.yaml"
expected_package_sha=d2d26ef7dc3c6e5579beb08ce5a6fdf28f091788ebfa2f45d30101cfb9746a0f
mode="${1:-check}"

for command in helm kubectl sops sha256sum; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
[[ "$mode" =~ ^(check|diff|apply|verify|rollback)$ ]] || {
  echo "usage: $0 check|diff|apply|verify|rollback" >&2; exit 2;
}
[[ "$(sha256sum "$package" | awk '{print $1}')" == "$expected_package_sha" ]] || {
  echo "CloudKitty package digest mismatch" >&2; exit 1;
}
sops filestatus "$secrets" | grep -q '"encrypted":true' || {
  echo "CloudKitty values must remain SOPS encrypted" >&2; exit 1;
}

work_dir="$(mktemp -d)"
chmod 700 "$work_dir"
trap 'rm -rf "$work_dir"' EXIT
sops -d "$secrets" >"$work_dir/secrets.yaml"
chmod 600 "$work_dir/secrets.yaml"
helm template "$release" "$package" -n "$namespace" -f "$values" -f "$work_dir/secrets.yaml" >"$work_dir/rendered.yaml"

if [[ "$mode" == check ]]; then
  kubectl apply --dry-run=server -n "$namespace" -f "$work_dir/rendered.yaml" >/dev/null
  kubectl apply --dry-run=server -f "$route" >/dev/null
  echo "CloudKitty server-side check passed"
  exit 0
fi

if [[ "$mode" == diff ]]; then
  if helm status "$release" -n "$namespace" >/dev/null 2>&1; then
    helm get manifest "$release" -n "$namespace" >"$work_dir/live.yaml"
    diff -u "$work_dir/live.yaml" "$work_dir/rendered.yaml" || test "$?" -eq 1
  else
    echo "CloudKitty is not installed; apply would create the rendered release"
    grep -E '^kind:|^  name:' "$work_dir/rendered.yaml"
  fi
  exit 0
fi

if [[ "$mode" == apply ]]; then
  : "${DCN_SITE_ROOT:?apply requires the canonical site repository path}"
  python3 "$root/deploy/scripts/verify-cloudkitty-source-lock.py" "$root" "$DCN_SITE_ROOT" >/dev/null
  helm upgrade --install "$release" "$package" -n "$namespace" \
    -f "$values" -f "$work_dir/secrets.yaml" --atomic --timeout 20m --wait
  kubectl apply -f "$route"
fi

if [[ "$mode" == rollback ]]; then
  previous="$(helm history "$release" -n "$namespace" -o json | python3 -c \
    'import json,sys; rows=[x for x in json.load(sys.stdin) if x["status"]=="superseded"]; print(rows[-1]["revision"] if rows else "")')"
  [[ -n "$previous" ]] || { echo "no accepted previous revision" >&2; exit 1; }
  helm rollback "$release" "$previous" -n "$namespace" --wait --timeout 20m
fi

kubectl rollout status -n "$namespace" deployment/cloudkitty-api --timeout=10m
kubectl rollout status -n "$namespace" deployment/cloudkitty-processor --timeout=10m
kubectl -n "$namespace" get endpoints cloudkitty-api -o jsonpath='{.subsets[0].addresses[0].ip}' >/dev/null
kubectl -n "$namespace" wait \
  --for='jsonpath={.status.parents[0].conditions[?(@.type=="Accepted")].status}=True' \
  httproute/openstack-public-rating --timeout=2m
kubectl -n "$namespace" get jobs -l application=cloudkitty -o json | python3 -c \
  'import json,sys; bad=[x["metadata"]["name"] for x in json.load(sys.stdin)["items"] if x.get("status",{}).get("failed",0)]; assert not bad,bad'
echo "CloudKitty API/processor and bootstrap jobs are ready"
