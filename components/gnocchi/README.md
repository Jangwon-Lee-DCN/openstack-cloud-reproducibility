# gnocchi operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `gnocchi`.

## Known issues and scope

## Affected baseline

- OpenStack-Helm tag `2026.1.0`, commit `c665eed`
- Chart version `2026.1.0`
- Chart application version `3.0.3`

## Symptoms

The chart defaults target an obsolete Gnocchi/Python runtime and cannot provide
the required modern Python 3.12, Keystone, MySQL, Tooz, and S3-compatible RGW
combination in this environment.

## Root cause

The chart metadata and runtime assumptions have not followed the current
Gnocchi packaging. Treating the unmodified chart as deployable would preserve
legacy Python paths and image expectations.

## Remediation

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

## Reconciliation

1. Ensure Rook-Ceph RGW, MariaDB, Keystone, Harbor, and the `openstack`
   namespace exist.
2. Re-encrypt the environment-profile Gnocchi Secrets for the target cloud.
3. Run `deploy/scripts/build-images.sh` when the pinned image is not already
   present in Harbor; commit any changed digest.
4. Run `deploy/scripts/reconcile.sh`. It applies the OBC, raises the RGW user
   bucket limit, bootstraps Keystone, and rolls out API and metricd.

The encrypted Gnocchi configuration contains environment-specific database,
Keystone, and RGW values. It is an exact profile for this PoC, not a universal
credential set. A new environment must regenerate it before reconciliation.

## Verification

- Two API and two metricd Pods are Ready and split across controllers.
- Both PodDisruptionBudgets allow one controlled disruption.
- `/metric/healthcheck` returns HTTP 200 through the public Gateway.
- The OBC is Bound and its RGW user permits at least ten buckets.
- A real Ceilometer measure creates rows in the Gnocchi metric and resource
  indexes and is retrievable through the authenticated API.

The last condition is currently pending in the PoC and is a release gate.
