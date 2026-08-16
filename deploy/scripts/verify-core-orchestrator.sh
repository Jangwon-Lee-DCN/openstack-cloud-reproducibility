#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
"$root/deploy/tests/core-orchestrator/run-contract-tests.sh"
"$root/images/horizon-core-orchestration-dashboard/verify-overlay.sh"
python3 - <<'PY' "$root/images/platform-core-orchestrator/openapi.yaml"
import sys, yaml
document = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
assert document["openapi"] == "3.1.0"
assert len(document["paths"]) >= 9
PY
grep -q 'CORE_ORCHESTRATOR_IMAGE must be pinned' "$root/automation/development/components/p0-core-orchestration.sh"
grep -q 'dcn.ssu.ac.kr/workload-class: development' "$root/automation/development/manifests/p0-core-orchestration.yaml"
if grep -Eq 'cloud\.dcn\.ssu\.ac\.kr|namespace: openstack|10\.67\.10\.6' \
  "$root/automation/development/manifests/p0-core-orchestration.yaml"; then
  echo 'production target leaked into development manifest' >&2; exit 1
fi
