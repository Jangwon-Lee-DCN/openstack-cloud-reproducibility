#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}

"$REPO_ROOT/deploy/scripts/verify-image-rebuild-closure.py"

python3 - "$REPO_ROOT/release-lock.yaml" <<'PYLOCK' | while read -r release expected; do
import sys,yaml
x=yaml.safe_load(open(sys.argv[1]))['spec']['releases']
for r in x: print(r['name'],r['chartVersion'])
PYLOCK
  actual=$(helm list -n "$NAMESPACE" -f "^${release}$" -o json     | python3 -c 'import json,sys; x=json.load(sys.stdin); print(x[0]["chart"].rsplit("-",1)[-1] if x else "missing")')
  [[ "$actual" == "$expected" ]] || {
    echo "$release version mismatch: expected $expected, got $actual" >&2; exit 1;
  }
done

for release in $(helm list -n "$NAMESPACE" -q); do
  status=$(helm status -n "$NAMESPACE" "$release" -o json     | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["status"])')
  [[ "$status" == deployed ]] || { echo "$release status=$status" >&2; exit 1; }
done

kubectl get pods -n "$NAMESPACE" -o json | python3 /dev/fd/3 3<<'PODCHECK'
import json
import sys

pods = json.load(sys.stdin)["items"]
bad = []
historical = []
for pod in pods:
    name = pod["metadata"]["name"]
    phase = pod.get("status", {}).get("phase", "Unknown")
    owners = pod["metadata"].get("ownerReferences", [])
    owner_kind = owners[0].get("kind") if owners else None
    if phase == "Succeeded":
        continue
    if phase == "Failed" and owner_kind in {None, "Job"}:
        historical.append(name)
        continue
    statuses = pod.get("status", {}).get("containerStatuses", [])
    if phase != "Running" or any(not status.get("ready", False) for status in statuses):
        bad.append(f"{name}: phase={phase}, owner={owner_kind or 'none'}")

for name in historical:
    print(f"warning: ignoring retained terminal test/job Pod: {name}", file=sys.stderr)
if bad:
    print("\n".join(bad), file=sys.stderr)
    raise SystemExit(1)
PODCHECK

for workload in octavia-api octavia-driver-agent octavia-housekeeping; do
  [[ "$(kubectl get deployment -n "$NAMESPACE" "$workload" -o jsonpath='{.status.readyReplicas}')" == "2" ]] || {
    echo "$workload does not have two ready replicas" >&2; exit 1;
  }
  [[ "$(kubectl get pods -n "$NAMESPACE" -l "application=octavia" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l)" -ge 2 ]] || {
    echo "Octavia replicas are not spread across two nodes" >&2; exit 1;
  }
done

[[ "$(curl -ksS -o /dev/null -w '%{http_code}' https://cloud.dcn.ssu.ac.kr/load-balancer/v2/lbaas/providers)" == "401" ]] || {
  echo "public Octavia route did not enforce Keystone authentication" >&2; exit 1;
}

for dashboard in skyline horizon; do
  component=skyline
  [[ "$dashboard" == horizon ]] && component=server
  [[ "$(kubectl get deployment -n "$NAMESPACE" "$dashboard" -o jsonpath='{.status.readyReplicas}')" == "2" ]] || {
    echo "$dashboard does not have two ready replicas" >&2; exit 1;
  }
  [[ "$(kubectl get pods -n "$NAMESPACE" -l "application=$dashboard,component=$component" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l)" -ge 2 ]] || {
    echo "$dashboard replicas are not spread across two nodes" >&2; exit 1;
  }
done

kubectl get pdb -n "$NAMESPACE" skyline >/dev/null
[[ "$(kubectl get deployment -n "$NAMESPACE" barbican-api -o jsonpath='{.status.readyReplicas}')" == "2" ]]
[[ "$(kubectl get pdb -n "$NAMESPACE" barbican-api -o jsonpath='{.spec.minAvailable}')" == "1" ]]
[[ "$(curl -ksS -o /dev/null -w '%{http_code}' https://cloud.dcn.ssu.ac.kr/key-manager/v1/secrets)" == "401" ]] || {
  echo "public Barbican route did not enforce Keystone authentication" >&2; exit 1;
}
kubectl get httproute -n "$NAMESPACE" openstack-public-services \
  -o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}' | grep -qx True

"$REPO_ROOT/deploy/scripts/verify.sh"
