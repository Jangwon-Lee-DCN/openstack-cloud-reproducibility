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

`reconcile-full-stack.sh` uses the patched Horizon chart's pod-local
django-compressor cache; no post-Helm ConfigMap mutation is required after the
Horizon Helm release. The chart renders the cache backend and probe timing as
declarative values, and its Deployment checksum performs any required rollout.
