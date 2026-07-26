# High Availability and Quorum

## Current Best-Effort HA Policy

The present two-controller deployment must maximize availability within its
physical and quorum constraints. The failure objective below applies to every
component unless a documented exception makes it technically impossible.

This policy applies to Kubernetes, Ceph, MariaDB/Galera, RabbitMQ, OVN
databases, API endpoints, ingress/load balancing, DNS, registry, secrets,
observability, and every OpenStack service installed in this phase:

- Place redundant stateless instances across both controllers with required
  anti-affinity or topology spread.
- Add tolerations for both controller scheduling policies, PodDisruptionBudgets,
  health probes, and stable endpoint failover.
- Use supported stateful HA topologies when they can survive either controller
  failure without split brain or data corruption.
- Treat single-node placement as an exception requiring a stated technical or
  physical constraint, outage impact, recovery procedure, and upgrade path.
- Prefer reproducible recovery over unsafe automatic failover when two nodes
  cannot form a safe majority quorum.
- Validate each service by testing the loss of either controller; record any
  dependency that prevents full service continuity.

## Failure Objective

The loss of either controller must preserve Kubernetes scheduling of existing
OpenStack control workloads, OpenStack APIs, database and message processing,
and established OVN networking.

Compute availability is separate. The loss of `cloud-controller-0` stops its
VMs because no second compute node currently exists.

## Quorum Analysis

| Component | Current/initial nodes | Required direction |
| --- | --- | --- |
| Kubernetes etcd | Two controllers | Three voting members in three failure domains |
| MariaDB/Galera | Not deployed | Three members or a supported external HA database |
| RabbitMQ | Not deployed | Three members with quorum queues |
| OVN NB/SB DB | Not deployed | Three RAFT members with persistent storage |
| API workloads | Two controllers | At least two replicas with anti-affinity |
| Provider gateway | One planned node | Add a tested redundant gateway design |
| BIND DNS | One node | Add secondary DNS or document as external dependency |
| Rook-Ceph | One MON, one MGR, one OSD on controller 0 | Three MON failure domains, redundant MGRs, and at least three OSD nodes |

## Third-Member Requirements

The third member may be a small independent host if it has reliable power,
networking, persistent storage where required, time synchronization, and a
separate failure domain. A witness cannot be assumed to work for every
component; each technology needs a supported topology.

## Scheduling Requirements

- Required anti-affinity for replicas of the same critical component
- Topology spread across nodes/failure domains
- PodDisruptionBudgets consistent with quorum
- Explicit tolerations for `cloud-controller-1`
- PriorityClasses for foundation services
- Resource requests and limits based on measured capacity
- Controlled drain and upgrade procedures

## Required Failure Tests

1. Power off `cloud-controller-0`.
2. Confirm Kubernetes API, etcd quorum, OpenStack APIs, database, RabbitMQ, and
   OVN control functions.
3. Restore node 0 and verify clean member rejoin.
4. Repeat for `cloud-controller-1`.
5. Test network partition separately from power loss.
6. Test stateful pod restart and persistent-volume reattachment.
7. Confirm that no split-brain or duplicate gateway ownership occurs.
