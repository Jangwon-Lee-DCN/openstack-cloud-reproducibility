#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
cd "$root/images/platform-core-orchestrator"
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 -m py_compile core/*.py
