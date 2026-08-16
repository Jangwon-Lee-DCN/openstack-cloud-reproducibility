#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
"$root/deploy/tests/core-orchestrator/run-contract-tests.sh"
grep -q 'CORE_ORCHESTRATOR_IMAGE must be pinned' "$root/automation/development/components/p0-core-orchestration.sh"
grep -q 'dcn.ssu.ac.kr/workload-class: development' "$root/automation/development/manifests/p0-core-orchestration.yaml"
if grep -Eq 'cloud\.dcn\.ssu\.ac\.kr|namespace: openstack|10\.67\.10\.6' \
  "$root/automation/development/manifests/p0-core-orchestration.yaml"; then
  echo 'production target leaked into development manifest' >&2; exit 1
fi
