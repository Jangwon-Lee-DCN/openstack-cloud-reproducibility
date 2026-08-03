# RECONCILE

1. Install the pinned CAPI/CAPO/ORC management controllers from
   `prerequisites/cluster-api/management-cluster`.
2. Apply `prerequisites/cluster-api/magnum-access/rbac.yaml`.
3. Run `deploy/scripts/sync-internal-ca.sh`.
4. Refresh the build context and build `images/magnum-capi` with the services
   repository's `images/magnum-capi/build.sh`.
5. Regenerate environment credentials with
   `deploy/scripts/generate-magnum-secrets.py`.
6. Run `deploy/scripts/install-magnum.sh`. It installs the pinned GitOps
   adapter image and package,
   reconciles the chart's post-install jobs in dependency order, applies both
   Gateway routes, reconciles the service catalog, and executes verification.
7. With the separately locked `magnum-capi-gitops` checkout, export
   `MAGNUM_CAPI_GITOPS_REPO_PATH` and `MAGNUM_CAPI_GITOPS_REVISION`, then run
   `deploy/scripts/install-magnum-capi-gitops.sh`. It installs Argo CD and
   Porch, seeds the exact accepted source into internal Gitea, provisions the
   scoped writer/reader credentials, and reconciles the ApplicationSet and
   two-replica repository writer. Production Phase 50 performs both steps.

The GitOps platform entry point intentionally does not run the PoC-specific
host-capacity script or force `maxPods=220` on production nodes.

Never materialize decrypted values in Git or place a static Kubernetes token
in values.

If a Nova server fails, correct the cloud/host cause and delete only its owning
CAPI Machine so its controller performs a clean replacement. Do not directly
remove Magnum database state while cluster-owned cloud resources remain.

For a legacy identity migration, temporarily retain an `openstack` cloud entry
matching the immutable old OpenStackCluster region until every replaced
Machine is deleted. Then restore `openstack` to `RegionOne-VM`; new
infrastructure resources use `openstack-capo`.

Repackage `openstack-cluster`, regenerate the repository index with the
current service URL, update `helm/packages/patched/SHA256SUMS`, and rerun the
repository installer as one atomic reconciliation. Validate Neutron quota
headroom before creating another cluster.
