#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$root"
python3 -m unittest -v \
  tests.test_resilience.EngineTest.test_backup_failure_always_thaws \
  tests.test_resilience.EngineTest.test_restart_resumes_without_duplicate_steps \
  tests.test_resilience.EngineTest.test_dr_fencing_is_fail_closed \
  tests.test_resilience.EngineTest.test_network_cross_project_is_rejected_and_no_probe_runs \
  tests.test_resilience.EngineTest.test_maintenance_failure_restores_scheduler_state \
  tests.test_resilience.EngineTest.test_image_promotion_requires_full_supply_chain
