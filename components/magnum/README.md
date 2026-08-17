# magnum operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `magnum`.

## Known issues and scope

The upstream OpenStack-Helm 2026.1.0 Magnum chart and Airship Noble image
cannot directly run the selected CAPI Helm driver:

- the image has only the legacy Heat driver and no Helm client;
- the CAPI driver expects a static kubeconfig token;
- CAPO and workload CCM require different catalog regions but must emit the
  same canonical Nova provider ID;
- the upstream driver forces an API load balancer and cannot exercise the
  explicitly experimental direct-floating-IP comparison;
- the Airship image lacks the chart's `magnum-api-wsgi` path;
- the chart's filter-style healthcheck is incompatible with the image's
  `oslo.middleware`;
- private-registry pulls, control-plane taints, and two-node HA require
  additional chart settings.
- OpenStack CCM did not tolerate the initial `NotReady` taint, creating a
  bootstrap ordering deadlock.
- Legacy clusters pinned `openstack/RegionOne` in immutable infrastructure
  identities. Reusing that cloud entry for `RegionOne-VM` prevented CAPO from
  deleting old Machines during an in-place chart migration.
- The internal repository index still advertised the retired
  `magnum-workload-chart-repository.capi-system` URL even though Magnum used
  the HA `magnum-chart-repository.openstack` service.
- The project default quota of 10 security groups was exhausted by two
  clusters and their Kubernetes LoadBalancer Services.
- A direct ORC v2.6 upgrade reset the HA overlay and left one controller
  replica.
- Magnum cleanup uses a label-selected Kubernetes Secret collection delete.
  Granting only the singular `delete` verb caused a hidden 403 and left
  clusters in `DELETE_IN_PROGRESS` after all CAPI/cloud resources were gone.

## Remediation

- Build from the pinned Airship Magnum digest and install
  `magnum-capi-helm==1.4.0` plus Helm `3.18.4`.
- Patch the driver to reread a projected ServiceAccount `tokenFile`.
- Generate both `openstack` (`RegionOne-VM`, workload add-ons) and
  `openstack-capo` (`RegionOne`, management CAPO) cloud entries.
- Select `openstack-capo` for infrastructure resources while omitting the
  Machine identity region, keeping provider IDs canonical.
- Honor `master_lb_enabled`; no-LB remains an experimental PoC mode.
- Add the CCM bootstrap toleration and make hardware-specific add-ons opt-in.
- Add the missing WSGI entry point.
- Patch the chart for CA/token file kubeconfig fields, registry pull secrets,
  and control-plane tolerations.
- Configure two API and two conductor replicas, required cross-node
  anti-affinity, and PDB `minAvailable: 1`.
- Override the Paste pipeline to omit the incompatible healthcheck filter.
- Enable CCM-managed LoadBalancer security groups in the workload chart.
- Preserve optional legacy cluster and Machine cloud selections so existing
  clusters can roll to the split `openstack`/`openstack-capo` identity model.
- Generate the repository index with
  `http://magnum-chart-repository.openstack.svc.cluster.local`.
- Set the PoC project quota to at least 50 security groups and 500 rules.
- Reapply two replicas, required hostname anti-affinity, and a PDB after every
  ORC upgrade.
- Grant the Magnum conductor `deletecollection` in addition to `delete` for
  the management resources covered by its CAPI ClusterRole.

The deployed image is pinned as:

`registry.dcn.ssu.ac.kr/openstack/magnum@sha256:4eda7acd9b7eea0c66662917a29151e22118e8ac89859017cc84a3948c5b426a`

## Reconciliation

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

## Verification

Run:

```bash
deploy/scripts/verify-magnum.sh
```

It verifies two ready API replicas, two ready conductor replicas, PDBs, both
the `k8s_capi_helm_v1` and `k8s_capi_gitops_v1` drivers, management-cluster Helm access, Gateway route
acceptance, and an authentication-enforced HTTP 401 from the internal API.

The Phase 50 GitOps reconciler additionally verifies Argo CD, Porch repository
sync, the deployment ApplicationSet, and two ready repository-writer replicas.

An authenticated `openstack coe cluster template list` must also complete.

The workload acceptance gate creates two minimal clusters:

- one control-plane and one worker behind an OVN Octavia API load balancer;
- one control-plane and one worker with a floating IP directly attached to the
  control-plane port.

For each cluster, verify two Ready nodes, all baseline Helm releases, DNS,
ClusterIP traffic, and Internet egress. The LB must be ACTIVE/ONLINE with a
TCP 6443 member. The no-LB cluster must have no matching Octavia load balancer.

The extended gate also verifies:

- Cinder CSI data survives a Pod restart and a worker Machine replacement;
- a Kubernetes LoadBalancer Service receives a floating IP and returns HTTP
  200 through an ACTIVE/ONLINE OVN Octavia pool member;
- create, delete, exact cloud-resource leak audit, and same-name recreation;
- controller-0 loss of CAPI, CAPO, ORC, Magnum API, and Magnum conductor Pods
  leaves controller-1 able to serve Magnum and reconcile workload clusters.

This Pod-level management failover does not prove physical-node HA. A
two-member management etcd cluster loses quorum when either host is lost; use
at least three management etcd members before claiming host-failure tolerance.

The live acceptance run passed all of the extended gates above. The lifecycle
test also proved that the corrected `deletecollection` RBAC removes the Magnum
record, generated Secrets, and application credential after CAPI finishes
cloud-resource deletion, and that the same Magnum cluster name can be reused.
