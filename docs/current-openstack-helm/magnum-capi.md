# Magnum with CAPI/CAPO

## Architecture

The host Kubernetes cluster is the Cluster API management cluster. Magnum uses
`magnum-capi-helm` to create CAPI resources there, and CAPO creates workload
cluster nodes as Nova VMs. Workload clusters are not nested in the management
cluster.

Magnum API and conductor, CAPI core, kubeadm bootstrap/control-plane, CAPO,
and ORC run with two replicas, required cross-node anti-affinity, leader
election, and a PodDisruptionBudget. The add-on provider is the intentional
exception: upstream requires one active replica to avoid reconciliation races.
An outage of that controller delays add-on changes but does not stop existing
workload clusters.

## Pinned artifacts

- OpenStack-Helm Magnum chart: `2026.1.0`, locally patched
- Magnum image:
  `registry.dcn.ssu.ac.kr/openstack/magnum@sha256:4eda7acd9b7eea0c66662917a29151e22118e8ac89859017cc84a3948c5b426a`
- Magnum CAPI Helm driver: `1.4.0`
- Magnum workload chart: `openstack-cluster` `0.26.0`, locally patched
- Cluster API add-on provider chart: `0.12.1`
- Helm client in the Magnum image: `3.18.4`
- CAPI: `v1.13.4`
- CAPO: `v0.14.6`, locally patched controller image
- CAPO image:
  `registry.dcn.ssu.ac.kr/openstack/capo-controller@sha256:91bfcbad65adfacd832ec6935011eee76790ac71b27e9d333d125a7d519f4cf8`
- ORC: `v2.5.0`
- Kubernetes workload image: `ubuntu-jammy-kube-v1.34.4-260217-1530`

## Local compatibility fixes

### Magnum image and chart

1. Add rotating projected-ServiceAccount `tokenFile` support.
2. Use the VM-routable internal Keystone endpoint when issuing workload
   cluster application credentials.
3. Emit two entries in each generated `clouds.yaml`:
   - `openstack` uses `RegionOne-VM` for CCM and Cinder CSI inside VMs.
   - `openstack-capo` uses `RegionOne` for CAPO in the management cluster.
4. Set `infrastructureCloudName: openstack-capo` in the workload chart.
   Machine identity references intentionally omit a region so CAPO and CCM
   agree on the canonical `openstack:///UUID` provider ID.
5. Honor Magnum's `master_lb_enabled` selection. Upstream intentionally forces
   a load balancer because upgrades without one are unreliable. The no-LB mode
   here is an explicitly experimental PoC comparison, not a production
   recommendation.
6. Add the missing `magnum-api-wsgi` entry point and correct the incompatible
   healthcheck middleware pipeline.

### Workload add-ons

1. Tolerate `node.kubernetes.io/not-ready:NoSchedule` in OpenStack CCM so it
   can initialize node addresses before ordinary workloads are schedulable.
2. Keep Calico, CCM, Cinder CSI, etcd-defrag, metrics-server, and
   node-problem-detector in the minimal baseline.
3. Disable NFD, NVIDIA GPU Operator, and Mellanox Network Operator by default.
   They are opt-in capabilities for clusters with matching hardware.

### CAPO

CAPO `v0.14.6` queried Neutron for one port with `Limit: 1`. This Neutron
deployment returns a pagination link when the result count equals the limit,
and Gophercloud then fails to decode that response. The pinned local image
changes the discovery limit to `2`; a single matching port is returned without
the invalid pagination path. The source pin and patch are preserved in the
reproducibility repository.

## Installation

1. Apply host tuning, including the persistent KVM device rule:
   `deployment/prerequisites/host-tuning/install.sh`.
2. Install management controllers:
   `deployment/prerequisites/cluster-api/management-cluster/scripts/install.sh`.
3. Install the add-on provider and internal workload-chart repository.
4. Apply `deployment/prerequisites/cluster-api/magnum-access/rbac.yaml`.
5. Synchronize the internal Gateway CA with `scripts/sync-internal-ca.sh`.
6. Build the exact Magnum image with
   `images/magnum-capi/build.sh`. The script refreshes the build-context
   ConfigMap before starting Kaniko, preventing stale source from being built.
7. Generate encrypted values and run `scripts/install-magnum.sh`.
8. Reconcile public/internal routes and the `RegionOne-VM` service catalog.
9. Import the pinned workload image and apply
   `manifests/magnum-workload-smoke-test.yaml`.

Do not commit decrypted credentials, application credentials, kubeconfigs, or
static Kubernetes bearer tokens.

## Acceptance scenarios

Both scenarios use exactly one control-plane and one worker VM:

| Scenario | API endpoint | Intended use |
|---|---|---|
| LB | OVN Octavia VIP with public floating IP | Supported/default topology |
| no-LB | Floating IP directly on the control-plane port | Experimental comparison only |

## Horizon contract

Project > Container Infra > Clusters is tailored to this deployment rather
than presenting the upstream Heat-oriented vocabulary. Cluster creation keeps
the public Magnum API schema unchanged and exposes the following flow:

1. choose the deployment profile and SSH key in the current Region;
2. size control-plane and worker groups, including autoscaling bounds;
3. select an isolated or existing Neutron network and the Kubernetes API
   endpoint exposure;
4. select CAPI machine-health remediation and optional add-ons;
5. review the exact topology, access policy and expected OpenStack/CAPI outputs
   before submission.

The workflow deliberately does not expose Magnum's raw `availability_zone`
field. With an existing Subnet, the driver reads the owning Neutron Network's
single approved `availability_zone_hints` rack. For a newly created overlay
network, it chooses one configured rack deterministically from the immutable
cluster UUID. That decision drives the CAPO control-plane/worker failure domain
and the matching `public-rack-N` external network together. Consequently a
tenant cannot accidentally place cluster VMs in one rack while placing the API
VIP/FIP path in another. Raw AZ remains observable to operators, not a normal
cluster-create choice.

The supported Octavia API endpoint, one control plane and one worker are the
UI defaults for the acceptance topology. A public API without allowed CIDRs is
explicitly flagged. The details view reports workload access, compute capacity,
effective labels, health and the Magnum -> Git -> Argo CD -> CAPI/CAPO flow;
legacy Heat stack fields are not treated as the source of truth.

Operational actions match that asynchronous lifecycle. Kubeconfig downloads
use an explicit `_kubeconfig.yaml` filename, resize is presented as worker node
group scaling, and rolling upgrade/resize actions are offered only from stable
`*_COMPLETE` states. The detail page shows the six request-to-ready phases,
GitOps ownership, node-group capacity, compatibility warnings and recovery
guidance.

The UI overlay is maintained under `images/horizon-magnum-dashboard`. Its
patcher asserts the exact upstream 18.0.0 source shape and fails the image build
if a future wheel cannot be patched completely. The same overlay is included
by the empty-Harbor `horizon-complete` build.

Run the per-cluster verifier after every add-on HelmRelease reaches
`Deployed`:

```bash
./scripts/verify-magnum-workload-cluster.sh <CAPI-name> lb
./scripts/verify-magnum-workload-cluster.sh <CAPI-name> no-lb
```

It verifies the endpoint mode, API TCP reachability, one Ready control-plane,
one Ready worker, baseline add-ons, workload scheduling, cluster DNS,
ClusterIP service traffic, and Internet HTTPS egress. Cold first boot can take
several minutes because Calico and CSI images are pulled independently by both
new Nova VMs.

For the LB scenario, additionally verify that Octavia reports one ACTIVE,
ONLINE load balancer and that its member targets the control-plane VM on TCP
6443. For no-LB, verify there is no corresponding Octavia load balancer and
that the endpoint floating IP is associated directly with the control-plane
Neutron port.

Workload Kubernetes `Service type=LoadBalancer` resources use the OVN Octavia
provider rather than Amphora. The vendored cloud-provider contract fixes
`lb-provider: ovn`, `lb-method: SOURCE_IP_PORT`, and
`provider-requires-serial-api-calls: true`; acceptance must confirm the
provider and real floating-IP traffic, not merely creation of a Service object.

## Safe reconciliation

- Before rolling a current repository writer over packages created by an
  older renderer, run the namespace ownership protection described in
  `magnum-capi-gitops/docs/namespace-ownership-migration.md`. The platform
  reconcile entry point applies the protection automatically. Detach stale
  Argo tracking only after every affected Application has synced a
  namespace-free revision.

- A Nova server in `ERROR` is not retried in place by CAPO. Correct the host or
  cloud cause, then delete only the owning CAPI `Machine`; the control-plane or
  MachineDeployment controller creates its replacement.
- Never delete a Magnum database row while CAPI, Nova, Neutron, Octavia, or
  Keystone resources still exist. Reconcile those resources first.
- If Magnum remains in `DELETE_IN_PROGRESS` after CAPI deletion, confirm all
  exact cluster-owned cloud resources are gone before removing the exact stale
  application credential, Kubernetes secrets, and database row.
- Keep operational incident timelines outside the public repositories. Only
  generalized issue, fix, reconcile, and verification guidance belongs here.
