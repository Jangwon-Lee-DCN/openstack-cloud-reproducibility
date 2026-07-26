#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
NAMESPACE=${NAMESPACE:-openstack}

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

kubectl get pods -n "$NAMESPACE" --no-headers   | awk '$3 !~ /Running|Completed/ {print; bad=1} END {exit bad}'

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
kubectl get httproute -n "$NAMESPACE" openstack-public-services \
  -o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}' | grep -qx True

"$REPO_ROOT/deploy/scripts/verify.sh"
