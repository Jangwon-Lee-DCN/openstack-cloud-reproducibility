# Skyline Fixes

1. Patch `skyline/templates/deployment.yaml` to render the standard
   helm-toolkit pod anti-affinity and toleration snippets.
2. Configure two Skyline replicas, required hostname anti-affinity, and a
   `minAvailable: 1` PodDisruptionBudget.
3. Generate the Skyline database password with `openssl rand -hex 32`; keep it
   and all other credentials only in SOPS-encrypted values.
4. Patch Horizon readiness and liveness probes to `/auth/login/`, the direct
   backend health endpoint that does not follow the externally prefixed login
   redirect.
5. Set Horizon `WEBROOT`, login/logout/static URLs, and `FORCE_SCRIPT_NAME` for
   `/horizon/`.
6. Route `/` to `skyline-api:9999` and `/horizon` to `horizon-int:80`, with the
   Horizon prefix removed by Gateway API.

The clean upstream packages remain under `helm/packages/upstream/`. Runtime
reconciliation uses `helm/packages/patched/skyline-2026.1.0.tgz` and
`helm/packages/patched/horizon-2026.1.0.tgz`, both locked by SHA-256.
