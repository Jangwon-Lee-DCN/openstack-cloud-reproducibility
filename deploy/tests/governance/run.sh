#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
cd "$root"
digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT

PYTHONPATH=services/governance-api/src \
  python3 -m unittest discover -s services/governance-api/tests -v
PYTHONPATH=services/governance-api/src:services/governance-worker/src \
  python3 -m unittest discover -s services/governance-worker/tests -v
PYTHONPATH=images/horizon-governance-dashboard \
  python3 -m unittest discover -s images/horizon-governance-dashboard/tests -v
python3 -m compileall -q services/governance-api/src
python3 -m compileall -q services/governance-worker/src
helm lint helm/governance --set-string "image.digest=$digest" --set-string "workerImage.digest=$digest"
if helm template governance helm/governance >/dev/null 2>&1; then
  echo 'chart accepted an unpinned image' >&2
  exit 1
fi
helm template governance helm/governance \
  --namespace development-p1-governance-services \
  --values helm/governance/development-values.yaml \
  --set-string "image.digest=$digest" --set-string "workerImage.digest=$digest" >"$rendered"

grep -q 'p1-governance-services.dev.dcn.ssu.ac.kr' "$rendered"
grep -q 'dcn.ssu.ac.kr/workload-class: development' "$rendered"
grep -q "@${digest}" "$rendered"
if grep -Eiq 'namespace: (openstack|production)$' "$rendered" ||
   grep -Eo '[A-Za-z0-9.-]+\.dcn\.ssu\.ac\.kr' "$rendered" |
     grep -Evq '(\.dev\.dcn\.ssu\.ac\.kr|^registry\.dcn\.ssu\.ac\.kr)$'; then
  echo 'rendered development manifest appears to contain a production target' >&2
  exit 1
fi
bash -n automation/development/components/p1-governance-services.sh
if rg -n --hidden -g '!*.md' \
  '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16})' \
  automation/development deploy/tests helm/governance images/governance-api \
  images/governance-worker images/horizon-governance-dashboard services; then
  echo 'potential committed credential found' >&2
  exit 1
fi
git diff --check
