# Storage Design

## Current Inventory

### `cloud-controller-0`

- Approximately 477 GB OS SSD
- Additional approximately 894 GB Intel SSD at `/dev/sdb`
- The additional disk is assigned to the single-node Rook-Ceph PoC as one
  BlueStore OSD.

### `cloud-controller-1`

- One approximately 894 GB SSD containing the OS and container storage
- No separate OpenStack storage device

## Storage Consumers

- MariaDB
- RabbitMQ
- OVN northbound and southbound databases
- Glance images
- Cinder volumes
- Optional monitoring and logging data

## Selected PoC Backend

The selected backend is the existing Rook-Ceph cluster in namespace
`rook-ceph`. OpenStack-Helm will consume its monitor configuration and
least-privilege client keys through the `ceph-adapter-rook` chart after the
OpenStack-Helm release is pinned.

Service separation:

| Consumer | Ceph interface | Pool or store | Ceph client |
| --- | --- | --- | --- |
| Cinder volumes | RBD | `cinder.volumes` | `client.cinder` |
| Cinder backup | RBD | `cinder.backups` | `client.cinderbackup` |
| Glance images | RBD | `glance.images` | `client.glance` |
| Nova ephemeral disks | RBD | `nova.vms` | `client.cinder` initially |
| Kubernetes PVCs | RBD CSI | `openstack-poc` | Rook CSI-managed |
| Object storage | Ceph RGW | `openstack-object-store` | RGW-managed |

Each OpenStack service pool is a separate Rook `CephBlockPool`. The PoC uses
replica size 1 because only one OSD exists. The production example uses
replica size 3 with `failureDomain: host`.

Client keys must be generated during the OpenStack integration stage with
least-privilege pool capabilities. Keyrings and rendered Kubernetes Secrets
must never be committed to Git.

## Object API Decision

Ceph is not a storage backend for native OpenStack Swift storage daemons.
These are separate object-storage implementations:

- Native OpenStack Swift and its chart are disabled for this PoC.
- Ceph RGW is the selected S3-compatible object API.
- RGW can expose a Swift-compatible API backed by Ceph and authenticated by
  Keystone, but the Rook integration is currently documented as experimental.
  It is not enabled in this project.

The PoC now deploys two RGW gateway replicas, one per controller, behind the
Rook-created ClusterIP service. This protects against an RGW Pod or controller
process failure while Ceph remains available. It does not remove the current
single-OSD failure domain: loss of `cloud-controller-0` still removes the
object data backend.

The authoritative mapping is
`values/site/storage/openstack-ceph-map.yaml`. Chart-specific Cinder, Glance,
Nova, and adapter overrides must be generated only after an immutable
OpenStack-Helm release is selected and its values schema is validated.

## Design Constraint

One extra disk on one node is not a highly available storage system. Using it
for all persistent services would make `cloud-controller-0` a storage single
point of failure and violate the controller-failure requirement.

## Production Design

1. Expand or replace Ceph with at least three storage failure domains.
2. Retain service-specific pools and migrate PoC data into replica-3 pools.
3. Run at least two RGW gateways across independent controller failure domains.
4. Reconsider native Swift or RGW Swift compatibility only if a future product
   requirement explicitly needs the Swift API.

A two-node Ceph cluster is not accepted as production HA. Local PVs may be used
only for explicitly disposable proof-of-concept data.

## Destructive-Change Gate

Before `/dev/sdb` is changed:

1. Confirm its serial number and stable `/dev/disk/by-id` path.
2. Mount or inspect it read-only and determine whether data must be retained.
3. Record owner approval for erasure.
4. Back up any retained data and test restoration.
5. Write and review an explicit rollback or replacement plan.
6. Use the stable by-id path, never an unverified `/dev/sdX` name, in the final
   destructive procedure.
