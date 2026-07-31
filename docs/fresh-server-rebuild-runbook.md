# Fresh Server Platform Rebuild Runbook

## Objective

Recreate the DCN Kubernetes management platform, OpenStack control plane, and
cloud extensions from newly installed Ubuntu Server 24.04 hosts. This runbook
is ordered; a failed gate stops the rebuild. It does not claim that stateless
reinstallation restores tenant data: Ceph, databases, object buckets, secrets,
DNS zones, and Git repositories require separate backups.

## Deployment profiles

| Property | `poc-two-node` | `production` |
| --- | --- | --- |
| Control-plane/etcd | Two members; no majority after one loss | Three or five members |
| Ceph | One explicitly selected OSD; data SPOF | At least three storage failure domains, replica 3 |
| Scheduling | A selected controller may also compute | Dedicated roles preferred |
| `eno1` | Management, SSH, DNS, Internet | Same unless the site design overrides it |
| `eno2` | Provider uplink to `br-ex` | Provider uplink, preferably redundant/bonded |
| Acceptance | Functional PoC | Node-loss, quorum, backup, and restore tests required |

The inventory is role-driven, so adding compute or storage nodes does not
require editing the playbooks. Do not copy PoC replica counts into production.

## Artifacts and trust boundary

1. `openstack-cloud-reproducibility` supplies pinned charts, patched packages,
   image build definitions, encrypted release values, and verification tools.
2. `openstack-cloud-services` supplies platform prerequisite manifests and
   site integration. Its Git commit is pinned in the Ansible inventory.
3. The age private identity, institutional CA keys, SSH private keys, database
   backups, Ceph keyrings, and break-glass credentials remain outside Git.
4. Mirror all container images and source archives into Harbor before an
   isolated rebuild. A Git checkout alone is not an offline backup.

Record SHA-256 checksums of both repository bundles and the offline secret
media. Use signed Git tags for accepted releases.

## Phase 0 — Site design and backups

Before installing any host, freeze:

- hostnames, BMC addresses, management IPs, DNS and NTP servers;
- the Kubernetes API VIP/FQDN, Pod CIDR, Service CIDR, and MTU;
- Gateway VIPs and DNS names (`cloud`, `internal.cloud`, platform, registry);
- the external network, currently `192.168.21.0/24`, gateway `.1`, allocation
  pool `.100-.200`;
- stable `/dev/disk/by-id/...` identifiers for every Ceph device;
- `eno1` management and `eno2` provider-network cabling on every applicable node.

Back up and restore-test etcd, MariaDB, Ceph/RGW, BIND zones, SOPS age keys,
Harbor metadata, Gitea, Grafana, and OpenStack credential material. Copying
Kubernetes YAML does not back up persistent application data.

## Phase 1 — Ubuntu installation and access

Install Ubuntu Server 24.04 with SSH, a named automation account, SSH public
keys, and passwordless sudo restricted according to site policy. Apply BIOS
virtualization/IOMMU settings and firmware updates. Verify remote console
access before touching networking.

On the Ansible control host:

```bash
sudo apt-get update
sudo apt-get install -y ansible-core git openssh-client
git clone https://github.com/Jangwon-Lee-DCN/openstack-cloud-reproducibility.git
git clone https://github.com/Jangwon-Lee-DCN/openstack-cloud-services.git
cd openstack-cloud-reproducibility/automation/ansible
cp -a inventory/poc-two-node inventory/local
```

Edit `inventory/local`. Use the production example for three-or-more-node
deployments. Replace every `REPLACE_...` value.

Gate:

```bash
./bin/preflight.sh inventory/local
```

## Phase 2 — Host baseline

```bash
ansible-playbook -i inventory/local/hosts.yml playbooks/10-hosts.yml
```

This disables swap, loads required modules, applies sysctls, installs CRI-O
and pinned Kubernetes packages, enables time/iSCSI services, installs Helm,
and creates an HAProxy/Keepalived Kubernetes API VIP. Validate SSH through
`eno1`, DNS, NTP, package holds, CRI-O, and VIP failover before continuing.

Rollback: restore the captured host configuration or reinstall the fresh OS.
Do not attempt an in-place network rollback without console access.

## Phase 3 — Kubernetes and Cilium

```bash
ansible-playbook -i inventory/local/hosts.yml playbooks/20-kubernetes.yml
ansible-playbook -i inventory/local/hosts.yml playbooks/30-cluster-baseline.yml
```

The first controller initializes kubeadm; remaining controllers and workers
join using short-lived credentials. Cilium runs with kube-proxy replacement,
VXLAN cluster-pool IPAM, Gateway API, LB-IPAM/L2 announcements, Hubble, and
metrics. The automation applies OpenStack role labels and untaints only a
controller explicitly carrying the `compute` role.

Gate: all Nodes are Ready; Cilium connectivity tests pass; etcd membership is
correct; API access survives stopping HAProxy on either controller.

## Phase 4 — Storage (explicit destructive boundary)

The playbook stops unless `confirm_ceph_device_wipe` is true. Before setting
it, compare `lsblk -e7 -o NAME,SIZE,MODEL,SERIAL,FSTYPE,MOUNTPOINTS` and
`wipefs -n` with every inventory `ceph_device`. Adapt and review the selected
Rook values profile; the existing PoC profile contains the old node name and
disk ID and must never be blindly reused.

For PoC, install one OSD, replica-1 pools, and document that controller loss
loses storage. For production, use at least three nodes/devices, MON count 3,
replica size/min-size 3/2, topology spread, and a dedicated recovery plan.
The required pools are `glance.images`, `cinder.volumes`, `cinder.backups`,
`nova.vms`, a Kubernetes RBD pool, and the RGW object store.

Disk wiping remains a separate, human-approved command. After it is complete,
set the confirmation and run Phase 5. This protects new servers from a wrong
inventory destroying an OS or data device.

## Phase 5 — Platform prerequisites

Mount the offline age key and run:

```bash
export SOPS_AGE_KEY_FILE=/media/offline/dcn-cloud.agekey
ansible-playbook -i inventory/local/hosts.yml playbooks/40-platform.yml
```

Dependency order is:

1. SOPS/age tooling and cert-manager;
2. reviewed Rook-Ceph profile and CSI;
3. Gateway API/Cilium VIP resources and public/internal Gateways;
4. BIND primary/secondary records and authoritative resolution;
5. Harbor backed by retained RGW storage;
6. Prometheus, Alertmanager, Grafana, Loki/Alloy, Hubble integration;
7. Octavia Valkey/Sentinel jobboard;
8. optional Gitea, Keycloak federation, CAPI/CAPO/ORC, and Magnum GitOps.

Run each component's own `preflight.sh`, `install.sh`, and `verify.sh`. The
Ansible role automates components whose accepted scripts are present. BIND
zone changes, provider `br-ex`, and the production Rook profile remain review
gates because a generic unattended change can remove management access or
data.

## Phase 6 — Provider network

With local console and a timed rollback, attach `eno2` to `br-ex` on every
compute/OVN gateway node. Do not assign the provider subnet to `eno2`; the
host management route remains on `eno1`. Validate OpenFlow, OVN chassis
registration, physical network mapping `external:br-ex`, MTU, upstream VLAN
mode, ARP, and direct egress from every gateway node.

Only after this gate create Neutron's external network with allocation range
`192.168.21.100-192.168.21.200` (or the new site's approved equivalent).

## Phase 7 — Pinned OpenStack

```bash
ansible-playbook -i inventory/local/hosts.yml playbooks/50-openstack.yml
```

The reconciler verifies package checksums, decrypts values only into a
temporary directory, installs OpenStack-Helm releases in dependency order,
applies custom telemetry resources, publishes routes, and runs verification.
Do not use Helm `--wait` for charts whose post-install hooks unblock API init
containers; the reconciler handles readiness explicitly.

After the core stack, reconcile Designate/PowerDNS, Amphora resources,
Magnum+CAPI/CAPO, Keycloak federation, Horizon/Skyline extensions, and the VPC
control plane/dashboard from their pinned repositories.

## Phase 8 — Acceptance and failure tests

```bash
ansible-playbook -i inventory/local/hosts.yml playbooks/60-verify.yml
```

In addition to script checks, create disposable tenants and verify identity,
image upload, VM boot, metadata, security groups, isolated overlapping VPC
CIDRs, SNAT/Floating IP Internet access, Cinder attach/mount/write/reboot,
Heat, Designate, Barbican, OVN and Amphora load balancers, Ironic API, and a
one-control-plane/one-worker Magnum cluster.

For production, repeat while draining or powering off each controller and
storage node individually. Record RTO/RPO and alert delivery. A two-member
etcd/OVN/MariaDB topology or a single OSD cannot pass full node-loss
acceptance, even if its Pods are spread across two hosts.

## Recovery versus clean rebuild

- **Clean rebuild:** creates an empty cloud using the pinned desired state.
- **Control-plane recovery:** restores etcd, databases, secrets, DNS, and
  persistent stores before reconciling workloads.
- **Tenant-data recovery:** restores Ceph/RGW and service databases as one
  consistent recovery point. Recreating Helm releases cannot recover volumes,
  images, objects, load balancers, or instance state.

Never run the clean-rebuild path against retained production disks until the
recovery path and ownership of every device are proven.
