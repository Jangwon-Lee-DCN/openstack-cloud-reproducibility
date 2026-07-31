# Project credential lifecycle runbook

The facade creates a 90-day Keystone application credential per project and
rotates it 14 days before expiry. It stores a replacement only after the new
credential authenticates. A superseded credential is deleted only when the
current user owns it; otherwise it remains until its finite expiry.

## Observe

- Grafana: **VPC Alertmanager Operations**, credential panels.
- Expiry: `vpc_project_credential_expiry_timestamp_seconds`.
- Results: `vpc_project_credential_rotations_total{outcome,reason}`.
- Metadata anomalies:
  `vpc_project_credential_binding_mismatches_total{reason}`.

## Manual rotation

1. Record only the Secret annotations for project, owner, credential ID, and
   expiry. Never print or copy `clouds.yaml`.
2. Delete only that project namespace's `openstack-credentials` Secret.
3. Make an authenticated facade request scoped to the project.
4. Verify the binding endpoint is `Ready`, expiry moved forward, and the
   success counter increased.
5. Confirm in Keystone that the old credential was deleted when owners match.
   If ownership differs, revoke it through that owner's administrative process
   or confirm its finite expiry.

Project mismatch, missing owner/payload, invalid expiry, and rotation-due
bindings are never accepted as fresh. Investigate the facade audit request ID
before rotating; do not patch annotations to make a binding appear valid.
