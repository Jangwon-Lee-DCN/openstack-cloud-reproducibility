# Requirements and Deployment Gates

## Functional Requirements

- Deploy OpenStack services as Kubernetes workloads using OpenStack-Helm.
- Run OpenStack control services on both controller nodes.
- Run Nova compute only on `cloud-controller-0` initially.
- Use Neutron ML2/OVN with Geneve tenant overlays.
- Preserve `eno1` for host access, internet egress, Kubernetes traffic, and
  primary OpenStack API/control connectivity.
- Use `eno2` as the physical provider/data uplink on compute nodes.
- Provide Heat orchestration APIs and engines.
- Deploy the Ironic API and control services, but keep provisioning,
  inspection, cleaning, and PXE/DHCP disabled until a dedicated provisioning
  VLAN, BMC inventory, images, and policy are approved.
- Provide persistent storage for every stateful control service.
- Produce immutable, reviewable chart values and image locks.

## Availability Requirement

A complete failure of either controller must not interrupt essential OpenStack
control functions or established VM networking beyond the approved RTO.

This requirement cannot currently be met by a two-member quorum. A third
failure domain is mandatory for etcd and is expected for MariaDB, RabbitMQ, and
OVN databases unless a supported alternative is documented and tested.

## Mandatory Gates

| Gate | Current status | Completion evidence |
| --- | --- | --- |
| Kubernetes/OpenStack-Helm version compatibility | PoC exception accepted | OpenStack-Helm `2026.1.0` on Kubernetes 1.36.3; pin commits/images and test render, rollback, and smoke paths |
| Third quorum failure domain | PoC exception accepted | No third member for PoC; manual recovery and no guaranteed RTO/RPO; third failure domain remains mandatory for production |
| API VIP and DNS plan | Configured; validation pending | `10.67.10.6`, `cloud.dcn.ssu.ac.kr`, and failover test |
| Provider network | Approved; host migration pending | Flat untagged `192.168.21.0/24`, pool `.100-.200`, multi-MAC allowed, console available, and timed rollback test |
| Storage backend | PoC approved | Rook-Ceph RBD and RGW/S3; single-OSD node-loss limitation accepted |
| `cloud-controller-0` extra disk disposition | Complete for PoC | Disk dedicated to the installed Rook-Ceph OSD |
| Backup and restore | Open | Successful etcd, database, and configuration restore test |
| Image supply chain | Open | Immutable image digest list and registry policy |

No production installation may start while a mandatory gate is blocked.

The Kubernetes 1.36.3 and two-node quorum exceptions authorize this PoC only.

## Non-Goals for the Foundation Milestone

- Magnum or managed Kubernetes service
- Custom VPC API implementation
- Transit routing or BGP fabric integration
- Compute high availability with only one compute node
- Multi-region deployment
