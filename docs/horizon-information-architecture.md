# Horizon Information Architecture and Panel Contract

## Goal

Horizon is organized around user tasks, not around the number of OpenStack
services installed. A visible project panel must answer all of these questions:

- what resource or decision does this page manage;
- whether it is project-facing or operator-facing;
- what the user can do there; and
- how it differs from adjacent panels.

Installing a dashboard package does not automatically justify exposing all of
its panels. Advanced service internals stay in `Admin` until the project user
has a supported workflow for them.

## Project navigation order

| Order | Group | User question | Primary panels |
|---:|---|---|---|
| 1 | Compute | Where do I create and operate instances? | Overview, Instances, Network Interfaces, Images, Key Pairs, Server Groups |
| 2 | Networking (VPC) | How are workloads connected, routed and protected? | Topology, VPCs, Subnets, routes, gateways, security, addresses, load balancers and connectivity |
| 3 | Block Storage | What persistent block devices and snapshots do instances use? | Volumes, Backups, Snapshots, Volume Groups |
| 4 | Shared File Storage | What NFS/CIFS-style filesystem can several clients mount? | File Shares, File Share Snapshots, File Share Networks |
| 5 | Object Storage | Where are object buckets and S3-compatible credentials managed? | S3 Access & Credentials, Swift Containers |
| 6 | Kubernetes | Where are managed Kubernetes clusters operated? | Clusters, Cluster Templates |
| 7 | DNS | Where are public and reverse DNS records managed? | Zones, Reverse DNS |
| 8 | Monitoring & Alarms | Are project resources measured, and which conditions need action? | Metric Coverage, Alerts & Alarms |
| 9 | Developer Tools | Where are API endpoints and downloadable credentials found? | API Access |

The stock Octavia `Load Balancers` entry is hidden from the VPC group because
the platform provides explicit Application and Network Load Balancer workflows.
Showing all three as peers implies three independent products and is misleading.

## Identity: users and project members

A **User Account** is a Keystone identity that can authenticate. A **Project
Member** is a role assignment connecting a user (or group) to one project.
They are related but not interchangeable:

- one user can belong to many projects with different roles;
- a user can exist without belonging to the currently selected project;
- removing a member revokes one project assignment but must not delete the
  login account; and
- deleting a user is an identity lifecycle operation affecting every project.

The primary workflow is therefore `Identity & Access > Projects & Members`:
select a project and use `Manage Members` to add/remove users and change roles.
`User Accounts` remains a distinct domain-administrator inventory for creating,
disabling or deleting identities. It is not a second membership screen and is
renamed to make that boundary explicit. `User Groups` and `Access Roles` follow
the same vocabulary.

## Shared File Storage

The `Shared File Storage` group is the Manila service. A File Share is a
network-mounted filesystem, unlike a Cinder Volume (block device attached to an
instance) or an S3 bucket (object API). Project users initially see only:

- **File Shares:** create and manage mountable shares and access rules;
- **File Share Snapshots:** point-in-time share recovery objects; and
- **File Share Networks:** the project network context used by a share service.

Security Services, Share Groups, Group Snapshots, User Messages and Resource
Locks are hidden from the project navigation because the current NFS workflow
does not require users to operate those advanced Manila internals. They remain
available to operators under `Admin > Shared File Storage` where appropriate.

## Monitoring boundary

The tenant group is `Monitoring & Alarms`; the operator panel is
`Admin > System > Telemetry Service Health`. Tenant pages never expose platform
Prometheus/Grafana internals or another project's telemetry. The detailed
screen contract lives in the telemetry dashboard's
`docs/product-specification.md`.

## Change and acceptance rules

1. Navigation names are product language; internal service names may appear in
   help text, not as unexplained top-level concepts.
2. Duplicate workflows are hidden rather than displayed side by side.
3. Project and Admin navigation are intentionally different.
4. The immutable Horizon image composes the existing VPC customization before
   applying navigation changes, preserving managed ENI and instance actions.
5. CI and live verification must assert group order, visible panel order,
   renamed labels and successful template loading on both Horizon replicas.
