# RECONCILE

1. Install the pinned CAPI/CAPO/ORC management controllers from
   `prerequisites/cluster-api/management-cluster`.
2. Apply `prerequisites/cluster-api/magnum-access/rbac.yaml`.
3. Run `deploy/scripts/sync-internal-ca.sh`.
4. Build `images/magnum-capi` with `deploy/manifests/magnum-image-build.yaml`.
5. Regenerate environment credentials with
   `deploy/scripts/generate-magnum-secrets.py`.
6. Run `deploy/scripts/install-magnum.sh`. It installs the pinned package,
   reconciles the chart's post-install jobs in dependency order, applies both
   Gateway routes, reconciles the service catalog, and executes verification.

Never materialize decrypted values in Git or place a static Kubernetes token
in values.
