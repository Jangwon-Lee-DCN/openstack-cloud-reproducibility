#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
namespace=openstack
release=cloudkitty
package="$root/helm/packages/patched/cloudkitty-2026.1.0.tgz"
values="$root/deploy/values/site/cloudkitty.yaml"
secrets="$root/deploy/secrets/cloudkitty.values.sops.yaml"
route="$root/deploy/manifests/cloudkitty-public-route.yaml"
expected_package_sha=51a49cef8791ce87f852a0117c9ef60c5f06dd3d0040e5e230f5b9db95549d66
mode="${1:-check}"

for command in helm kubectl sops sha256sum; do
  command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }
done
[[ "$mode" =~ ^(check|diff|apply|verify|rollback|retry-storage-init)$ ]] || {
  echo "usage: $0 check|diff|apply|verify|rollback|retry-storage-init" >&2; exit 2;
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

if [[ "$mode" == retry-storage-init ]]; then
  helm status "$release" -n "$namespace" >/dev/null || {
    echo "CloudKitty release must exist before retrying storage-init" >&2; exit 1;
  }
  kubectl delete job -n "$namespace" cloudkitty-storage-init --ignore-not-found --wait=true
  python3 - "$work_dir/rendered.yaml" <<'PY' | kubectl apply -n openstack -f -
import sys
import yaml

matches = [
    doc for doc in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8"))
    if doc and doc.get("kind") == "Job"
    and doc.get("metadata", {}).get("name") == "cloudkitty-storage-init"
]
if len(matches) != 1:
    raise SystemExit(f"expected one cloudkitty-storage-init Job, found {len(matches)}")
yaml.safe_dump(matches[0], sys.stdout, sort_keys=False)
PY
  if ! kubectl wait -n "$namespace" --for=condition=complete \
    job/cloudkitty-storage-init --timeout=10m; then
    kubectl describe job -n "$namespace" cloudkitty-storage-init
    kubectl logs -n "$namespace" job/cloudkitty-storage-init --all-containers=true --tail=-1 || true
    exit 1
  fi
  echo "CloudKitty storage-init retry completed"
  exit 0
fi

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
  release_status="$(helm status "$release" -n "$namespace" -o json 2>/dev/null | \
    python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["status"])' || true)"
  if [[ "$release_status" == pending-install ]]; then
    helm uninstall "$release" -n "$namespace" --wait --timeout 10m
  elif [[ -n "$release_status" && "$release_status" != deployed ]]; then
    echo "refusing to mutate CloudKitty release in status: $release_status" >&2
    exit 1
  fi
  # Hook failures from an interrupted older chart may leave the same ephemeral
  # names without Helm ownership. Always reconcile this exact bounded set.
  kubectl delete job -n "$namespace" --ignore-not-found --wait=true \
    cloudkitty-bootstrap cloudkitty-db-init cloudkitty-db-sync cloudkitty-rabbit-init \
    cloudkitty-storage-init cloudkitty-ks-service cloudkitty-ks-endpoints \
    cloudkitty-ks-user
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
