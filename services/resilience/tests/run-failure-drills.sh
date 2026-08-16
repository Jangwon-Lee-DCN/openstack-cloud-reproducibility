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
  tests.test_resilience.EngineTest.test_image_promotion_requires_full_supply_chain \
  tests.test_contracts_and_policies.LeaseCheckpointTest.test_lease_exclusion_expiry_and_checkpoint \
  tests.test_contracts_and_policies.BackupPolicyTest.test_retention_preserves_hold_restore_reference_and_latest_success \
  tests.test_contracts_and_policies.NetworkExplanationTest.test_declared_allowed_but_probe_failed_is_mismatch \
  tests.test_contracts_and_policies.MaintenanceMatrixTest.test_masakari_lock_blocks_competing_campaign \
  tests.test_contracts_and_policies.ImageAttestationTest.test_revocation_forces_deactivation \
  tests.test_controlplane_e2e.ControlPlaneTest.test_provider_failure_is_visible_and_retryable \
  tests.test_controlplane_e2e.ControlPlaneTest.test_controller_restart_observes_completed_resource_without_duplicate_provider_call \
  tests.test_controlplane_e2e.ProductionConfigTest.test_production_mode_is_unconditionally_fail_closed_without_real_clients \
  tests.test_contracts_and_policies.CrossTrackFixtureTest.test_track_a_schema_rejects_legacy_lowercase_state \
  tests.test_contracts_and_policies.CrossTrackFixtureTest.test_track_b_schema_rejects_legacy_event_and_extra_top_level_field
