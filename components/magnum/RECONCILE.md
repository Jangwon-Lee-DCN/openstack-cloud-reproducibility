# RECONCILE

1. Install the pinned CAPI/CAPO/ORC management controllers from
   `prerequisites/cluster-api/management-cluster`.
2. Apply `prerequisites/cluster-api/magnum-access/rbac.yaml`.
3. Run `deploy/scripts/sync-internal-ca.sh`.
4. Build `images/magnum-capi` with `deploy/manifests/magnum-image-build.yaml`.
5. Regenerate environment credentials with
   `deploy/scripts/generate-magnum-secrets.py`.
6. Install `helm/packages/patched/magnum-2026.1.0.tgz` with
   `deploy/values/site/magnum.yaml` and decrypted
   `deploy/secrets/magnum.values.sops.yaml`.
7. Apply public/internal Gateway routes and run the internal catalog
   reconciler.

Never materialize decrypted values in Git or place a static Kubernetes token
in values.
