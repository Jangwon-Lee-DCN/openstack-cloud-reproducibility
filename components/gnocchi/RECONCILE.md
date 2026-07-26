# RECONCILE: Gnocchi

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
