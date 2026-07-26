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
"$REPO_ROOT/deploy/scripts/verify.sh"
