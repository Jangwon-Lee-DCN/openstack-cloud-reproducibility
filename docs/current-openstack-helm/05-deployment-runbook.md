# Deployment Runbook

## Current Execution Record

The PoC execution started on 2026-07-25 with the pinned OpenStack-Helm
`2026.1.0` source. Installed and smoke-tested releases are:

1. `ceph-adapter-rook`
2. `mariadb`, `rabbitmq`, and `memcached`
3. `keystone`
4. `placement`
5. `glance` using `glance.images` through RBD
6. `cinder` using `cinder.volumes` and `cinder.backups` through RBD
7. `openvswitch` on both provider-connected nodes
8. `ovn` with three-member NB/SB databases, two northd replicas, and two gateway chassis
9. `neutron` with two API replicas and OVN metadata agents on both nodes
10. `libvirt` and `nova`, with HA control services and one KVM compute on `cloud-controller-0`
11. `heat` with two API, CFN, and engine replicas
12. `horizon` with two dashboard replicas
13. control-only `ironic` with two API and two conductor replicas

All public catalog URLs use path-based endpoints beneath
`https://cloud.dcn.ssu.ac.kr`. Gateway API routes are activated separately
when each backend is ready. Upstream Helm hooks must be installed without
Helm `--wait`: API init containers depend on post-install Jobs, so `--wait`
creates a lifecycle deadlock. Readiness is checked explicitly after hooks
finish.

Site overrides pin `rabbit_init` to
`quay.io/airshipit/rabbitmq:3.10.18-management`; the default Docker Hub image
was unreliable through the local registry path. Existing Rook pools use the
standard `rbd` application tag, so Glance and Cinder storage-init overrides
must retain that tag. Secrets are stored only in age/SOPS-encrypted values. The Nova storage-init template is site-patched to pass Ceph's explicit confirmation flag when setting a pool to replication 1. Glance, Cinder, and Nova PoC RBD pools are configured for replication 1; this is never a production recommendation.

The provider network `public` is ACTIVE with physical network `external`, CIDR `192.168.21.0/24`, gateway `192.168.21.1`, DHCP disabled, and the inclusive allocation pool `192.168.21.100-192.168.21.200`. The exposed `client.cinder` key was revoked and rotated on 2026-07-25; Cinder, Libvirt, and Nova compute were restarted and an RBD volume create/delete smoke test passed.

Gateway API publishes Keystone, Placement, Glance, Cinder, Neutron, Nova, Heat, Ironic, and Horizon beneath `https://cloud.dcn.ssu.ac.kr`. The route is stored in `manifests/openstack-public-routes.yaml`. Ironic uses verified `2026.1-ubuntu_noble` Airship images. Its upstream chart toleration indentation and missing API worker default are site-patched; PXE, TFTP, HTTP boot, cleaning-network management, bootstrap image download, and object-store bootstrap are disabled.

## Phase A — Read-Only Inventory

- Run `scripts/preflight.sh`.
- Export Kubernetes resources and etcd membership.
- Inventory both hosts, BIND, routes, addresses, firewall, modules, mounts, and
  stable disk identifiers.
- Record Kubernetes Service CIDR and Cilium configuration.
- Confirm time synchronization and name resolution.

Expected result: a complete, reviewable inventory with no system changes.

Rollback: not applicable.

## Phase B — Design Closure

- Resolve all `TBD` values in `config/site.yaml`.
- Use OpenStack-Helm `2026.1.0` on Kubernetes 1.36.3 for this PoC and resolve
  its tags to exact commits and image digests.
- Select storage, API VIP, Gateway API controller, load balancer, DNS, TLS, and
  provider-network designs.
- Resolve the third-member topology.

Expected result: every mandatory gate in `00-requirements.md` is complete.

Rollback: revert documentation and configuration changes in Git.

## Phase C — Pin and Render

- Pin upstream source commits and images by digest.
- Build chart-specific value layers.
- Render all charts without applying them.
- Run schema checks, policy checks, and secret scans.
- Review hostNetwork, privileged containers, hostPath mounts, hooks, jobs,
  tolerations, affinity, PDBs, Services, and PVCs.

Expected result: deterministic rendered manifests and a review record.

Rollback: discard generated output; no cluster change occurs.

## Phase D — Foundation Deployment

Deploy incrementally in dependency order. After every component:

- Wait for readiness.
- Run chart tests where supported.
- Validate logs, endpoints, persistence, and restart behavior.
- Record the exact command and release revision.
- Stop on any unexplained warning or degraded state.

Rollback: use the component-specific rollback procedure validated during the
render phase. Stateful rollback requires a tested data compatibility plan.

## Phase E — Compute and Networking

- Apply node labels only after reviewing chart selectors.
- Prepare OVS/OVN on intended nodes.
- Migrate `eno2` to `br-ex` with console access and a timed rollback mechanism.
- Deploy Neutron, libvirt, and Nova.
- Validate provider, tenant, SNAT, Floating IP, security-group, DHCP, metadata,
  and MTU behavior.

Rollback: restore the saved network configuration from local console access;
remove only resources created by this phase.

## Phase F — Acceptance and Failure Testing

- Create a test project, network, subnet, router, image, flavor, and instance.
- Validate east-west and north-south traffic.
- Validate volume attach/detach and instance reboot.
- Run the failure tests in `04-ha-and-quorum.md`.
- Record RTO/RPO and any manual intervention.

The environment is not production-ready until every acceptance criterion and
failure test has passed.

## Phase G — Heat

- Deploy Heat API and engines and publish `/orchestration`.
- Validate stack create, update, rollback, delete, and controller restart.

## Phase H — Ironic Bare Metal

- Deploy Ironic API and conductor control services only.
- Keep provisioning, inspection, cleaning, and PXE/DHCP disabled.
- Do not enroll hardware until an isolated provisioning VLAN, BMC inventory,
  checksum-pinned images, and an approved cleaning policy exist.
- Treat actual enrollment and deployment validation as a later activation phase.

Ironic must not manage either Kubernetes controller as a tenant bare-metal node.
