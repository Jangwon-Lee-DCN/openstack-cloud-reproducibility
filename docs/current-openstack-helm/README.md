# OpenStack-Helm Deployment

## Status

This directory is the reproducible deployment workspace for the OpenStack
foundation. It contains specifications, site inventory, version pins, Helm
value overrides, manifests, and operational scripts.

External platform dependencies are owned by the sibling
[`deployment/prerequisites/`](../prerequisites/README.md) workspace. Its
component matrix defines which lifecycle belongs here and which does not.

The PoC foundation deployment is operational. As of 2026-08-04, the following
OpenStack-Helm `2026.1.0` releases are installed and healthy in the `openstack`
namespace:

- `ceph-adapter-rook`
- `mariadb` with three Galera members on Ceph RBD PVCs
- `rabbitmq` with three members on Ceph RBD PVCs
- `memcached` with two members
- `keystone` with two API replicas
- `placement` with two API replicas
- `glance` with two API replicas and the `glance.images` RBD pool
- `cinder` with two API replicas, two schedulers, one volume worker, and one
  backup worker; volumes and backups use dedicated RBD pools
- `openvswitch` and `ovn` on both provider-connected nodes; OVN NB and SB use
  three-member Ceph-backed databases and both nodes are gateway chassis
- `neutron` with two API replicas, two OVN metadata agents, and FWaaS v2 using
  the upstream OVN service driver
- `libvirt` and `nova`; Nova control services have two replicas and
  `cloud-controller-0` is registered as the active KVM compute
- `heat` with two API, CFN, and engine replicas
- `horizon` with two dashboard replicas
- `magnum` with the CAPI GitOps driver, backed by CAPI/CAPO/ORC, Argo CD,
  Porch and the repository writer
- control-only `ironic` with two API and two conductor replicas; PXE, HTTP boot,
  cleaning-network creation, image bootstrap, and hardware enrollment are disabled

The one-replica Cinder volume and backup workers are intentional PoC storage
exceptions because only `cloud-controller-0` owns the Ceph OSD disk. The external Neutron network `public` is active on `external` with allocation pool `192.168.21.100-192.168.21.200`.

The deployment remains **blocked for production execution** by the
remaining HA design gate:

1. Two controller nodes cannot safely provide one-node-failure tolerance for
   majority-quorum services without a third member or witness.

OpenStack-Helm `2026.1.0` on Kubernetes 1.36.3 is the operator-approved PoC
baseline and compatibility exception. It is not a production support claim;
tags must be resolved to exact commits and images locked by digest.

## Deployment Scope

The initial OpenStack foundation includes:

- Keystone
- Placement
- Glance
- Nova
- Neutron with ML2/OVN
- Cinder
- Heat
- Ironic
- Horizon
- MariaDB
- RabbitMQ
- Memcached
- OVN northbound and southbound databases
- OpenStack API exposure through Gateway API and a load-balancer implementation
- Persistent storage for stateful services

Heat follows core-service validation. Ironic has a dedicated bare-metal phase
requiring a provisioning network, BMC inventory, deploy images, cleaning
policy, and conductor placement.

Octavia, Designate, Barbican, monitoring, and logging have passed their PoC
deployment phases. The exact Designate and PowerDNS chart fixes and packages
are preserved in this repository.

Horizon HA static asset behavior and its required verification are documented
in [`18-horizon-ha-static-assets.md`](18-horizon-ha-static-assets.md).

Magnum, CAPI, CAPO and ORC are part of the accepted managed-Kubernetes path.
Magnum requests render approval-gated Git packages which Argo CD reconciles on
the management cluster. The exact topology and operational contract are in
[`magnum-capi.md`](magnum-capi.md); renderer source and migration procedures
are pinned in the sibling `magnum-capi-gitops` repository.

## Repository Layout

```text
deployment/openstack-helm/
├── README.md
├── config/
│   ├── site.yaml
│   └── versions.env
├── docs/
│   ├── 00-requirements.md
│   ├── 01-architecture.md
│   ├── 02-network.md
│   ├── 03-storage.md
│   ├── 04-ha-and-quorum.md
│   └── 05-deployment-runbook.md
├── manifests/
├── scripts/
│   ├── preflight.sh
│   └── render.sh
├── values/
│   ├── common/
│   └── site/
└── vendor/
```

The `vendor/` directory is reserved for pinned upstream source checkouts and is
not committed. Version pins are committed in `config/versions.env`.

## Configuration Workflow

1. Resolve every item marked `TBD` in `config/site.yaml`.
2. Record the Kubernetes 1.36 PoC exception and resolve the quorum gate.
3. Select immutable OpenStack-Helm and image references in `versions.env`.
4. Run `scripts/preflight.sh` from `cloud-controller-0`.
5. Fetch the pinned upstream repositories into `vendor/`.
6. Generate chart-specific site overrides under `values/site/`.
7. Run `scripts/render.sh` and review all rendered Kubernetes resources.
8. Back up Kubernetes, DNS, network, and host configuration.
9. Deploy one component at a time using the runbook.
10. Execute functional and one-controller-failure tests.

## Safety Rules

- Never run an upstream environment bootstrap or firewall-clearing playbook on
  this existing Kubernetes cluster.
- Never move an address or default route from `eno1` during unattended work.
- Attach a compute/provider bridge such as `br-ex` to `eno2`, never `eno1`.
- Do not erase a disk until its identity, contents, ownership, and rollback
  plan have been independently verified.
- Do not deploy unpinned charts or images.
- Do not store passwords, kubeconfigs, private keys, or rendered Secrets here.
- Use `helm upgrade --install --atomic` only after chart hooks and rollback
  behavior have been tested for that component.

## Current Node Intent

| Node | Control | Compute | Cinder volume | Object storage | Primary uplink | Data/provider uplink |
| --- | --- | --- | --- | --- | --- | --- |
| `cloud-controller-0` | Yes | Yes | Yes | Yes | `eno1` / `192.168.21.10` | addressless `eno2` on `br-ex` |
| `cloud-controller-1` | Yes | No | No | No | `eno1` / `192.168.21.12` | addressless `eno2` on `br-ex` |

Node roles are declared in `config/node-roles.yaml` and applied idempotently by
`scripts/apply-node-labels.sh`. Storage labels are paired with the Cinder
selector overrides under `values/site/`; native Swift is disabled.

The approved PoC network uses Neutron ML2/OVN, Geneve tenant overlays over
`eno1`, and a flat `192.168.21.0/24` external provider network on
`br-ex -> eno2`. The management network remains `/24`; VPC address-space scale
does not require enlarging the host L2 domain. The inclusive external allocation
pool is `192.168.21.100-192.168.21.200`. See `docs/02-network.md`.

Both controllers and every future compute are provider-connected OVN gateway
chassis. Distributed Floating IP is enabled so FIP traffic exits locally on
the VM's compute. Ordinary SNAT for VMs without a FIP remains an OVN gateway
chassis path and is not claimed to be compute-local.

The operator approved the two-node PoC quorum exception, untagged multi-MAC
provider ports, and console-backed network maintenance. Ceph RGW/S3 is the
object API; the native Swift chart is disabled. Ironic API/control services are
in scope, while provisioning, inspection, cleaning, and PXE/DHCP remain gated
on a dedicated provisioning VLAN and hardware inventory.

## Documentation Index

- [Requirements](docs/00-requirements.md)
- [Architecture](docs/01-architecture.md)
- [Network design](docs/02-network.md)
- [Storage design](docs/03-storage.md)
- [HA and quorum](docs/04-ha-and-quorum.md)
- [Deployment runbook](docs/05-deployment-runbook.md)
- [Provider bridge runbook](docs/06-provider-bridge-runbook.md)
- [Neutron network acceptance](docs/07-network-acceptance.md)
- [Neutron FWaaS v2 with ML2/OVN](docs/11-neutron-fwaas-v2.md)
