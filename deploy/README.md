# Deployment Inputs

This directory is the local correction layer over the clean charts under
`helm/openstack-helm`.

- `values`: non-secret OpenStack-Helm overrides
- `secrets`: SOPS-encrypted Helm values and Kubernetes Secrets
- `manifests`: custom image builders and resources not safely supplied by the
  upstream charts
- `scripts`: idempotent reconciliation and verification commands

Do not hand-edit live resources without translating the change back into this
directory and recording it in the component ISSUE/FIX documents.

`reconcile-full-stack.sh` runs `ensure-horizon-static-ownership.sh` after the
Horizon Helm release. This idempotently patches the chart-generated startup
script so runtime asset compression can write to the per-Pod static volume,
then restarts Horizon before waiting for rollout health.
