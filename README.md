# OpenStack Cloud Reproducibility Kit

This repository preserves known-good OpenStack-Helm inputs and every local
compatibility fix required by the DCN cloud deployment. Its Git history is
part of the design:

1. the first commit imports immutable upstream baselines;
2. later commits add local image, values, manifest, and chart fixes;
3. reconciliation and verification documents explain how to reproduce them.

Never edit an upstream baseline silently. Any deviation must have an ISSUE,
FIX, RECONCILE, and VERIFY record and a separate commit.

## Layout

- `helm/openstack-helm`: clean OpenStack-Helm chart sources
- `helm/packages/upstream`: packaged upstream charts with SHA-256 checksums
- `helm/packages/patched`: locally patched chart packages, when required
- `images`: immutable base-image provenance and local Dockerfiles
- `components`: component-specific problem and operational records
- `deploy`: values, manifests, encrypted secrets, and reconciliation scripts
- `docs`: repository policy and provenance

The initial scope is Gnocchi, Ceilometer, and Aodh. Additional OpenStack
components should follow the same history and documentation model.
