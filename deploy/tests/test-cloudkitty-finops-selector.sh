#!/usr/bin/env bash
set -euo pipefail

GOVERNANCE_FINOPS_SELECTOR_TEST=1 source "$(dirname "$0")/cloudkitty-finops-acceptance.sh"

kubectl() {
  printf '%s\n' '{
    "items": [
      {"metadata":{"name":"old","deletionTimestamp":"2026-08-17T00:00:00Z"},
       "status":{"containerStatuses":[{"name":"api","ready":true},{"name":"worker","ready":true}]}},
      {"metadata":{"name":"starting"},
       "status":{"containerStatuses":[{"name":"api","ready":true},{"name":"worker","ready":false}]}},
      {"metadata":{"name":"ready"},
       "status":{"containerStatuses":[{"name":"api","ready":true},{"name":"worker","ready":true}]}}
    ]
  }'
}

selected=$(select_ready_pod development app=governance api worker)
[[ $selected == ready ]]
printf 'ready non-terminating selector: PASS\n'
