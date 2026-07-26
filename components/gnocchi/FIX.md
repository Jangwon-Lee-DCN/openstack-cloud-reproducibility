# FIX: Modern Gnocchi Runtime and Declarative Deployment

- Build Gnocchi 4.7.0 from `images/gnocchi/Dockerfile`.
- Pin the resulting image through the deployment manifest.
- Use MariaDB for the indexer and MySQL Tooz coordination.
- Use a Rook-Ceph RGW ObjectBucketClaim for measures and aggregates.
- Run two API and two metricd replicas with hard hostname anti-affinity and
  PodDisruptionBudgets.
- Register Keystone endpoints for `/metric`.
- Store runtime and full configuration Secrets with SOPS.

The upstream chart remains untouched for comparison. The replacement manifests
are under `deploy/manifests/gnocchi-*.yaml`.
