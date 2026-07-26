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

The repository now contains every OpenStack-Helm chart used by the accepted
PoC, all final release values snapshots, the three deployed chart patches, and
the custom Gnocchi/Ceilometer/Aodh images and manifests. It is the immutable
artifact source consumed by `openstack-cloud-services`.

## Inspect and run

```bash
# Show every local change above the upstream baseline.
git diff 4c3a128..HEAD

# Rebuild images only when the pinned artifacts are unavailable.
BUILD_IMAGES=1 ./deploy/scripts/reconcile-full-stack.sh

# Reuse already-pinned images and reconcile the stack.
./deploy/scripts/reconcile-full-stack.sh

# Repeat non-mutating health checks.
./deploy/scripts/verify-full-stack.sh
```

Read each component's `ISSUE.md`, `FIX.md`, `RECONCILE.md`, and `VERIFY.md`
before using the environment-specific encrypted profile on another cloud.
