#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
export ONLY_RELEASE=ironic
export VERIFY_AFTER_RECONCILE=0
"$root/deploy/scripts/reconcile-full-stack.sh"
"$root/deploy/scripts/verify-ironic-physical-provisioning.sh"
