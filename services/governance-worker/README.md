# Governance worker contract

The first development slice includes secret-free workflow state machines for
budget thresholds, certificate overlap/cleanup and fenced two-phase rotation.
It deliberately runs no credential-bearing adapter. Async delivery, CA/ACME,
Barbican rotation and telemetry collectors consume the API contracts only after
their development Secrets, egress allowlists and Track A checkpoint contract
are available. Queue payloads contain resource IDs, `operation_id`, and
`request_id`; they never contain private keys, tokens, webhook secrets or
rotated credential values.

This fail-closed boundary prevents an API proof from being mistaken for a live
certificate or credential rotation deployment.
