#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 -m py_compile "$root"/dcn_core_orchestration/*.py "$root"/enabled/*.py
grep -q '/launch-templates' "$root/dcn_core_orchestration/static/dcn_core_orchestration/catalog.js"
grep -q '/auto-scaling-groups' "$root/dcn_core_orchestration/static/dcn_core_orchestration/catalog.js"
grep -q '/recycle-bin' "$root/dcn_core_orchestration/static/dcn_core_orchestration/catalog.js"
