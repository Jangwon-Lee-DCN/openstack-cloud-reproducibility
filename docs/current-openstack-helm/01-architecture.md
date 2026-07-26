# Deployment Architecture

## Control Plane

OpenStack API pods are distributed across both Kubernetes nodes with required
anti-affinity and topology spread. Kubernetes Services provide stable internal
endpoints. External APIs use Gateway API through an approved gateway
controller and load-balancer implementation.

Stateful systems use component-supported clustering and persistent volumes.
Replica counts alone do not constitute high availability; quorum membership,
storage placement, fencing, disruption budgets, and recovery behavior must all
be validated.

## Node Labels

Planned labels:

```text
cloud-controller-0:
  openstack-control-plane=enabled
  openstack-compute-node=enabled
  openvswitch=enabled
  openstack-network-gateway=enabled
  openstack-cinder-volume=enabled
  openstack-object-storage=enabled

cloud-controller-1:
  openstack-control-plane=enabled
  openvswitch=enabled
  openstack-network-gateway=enabled
```

Exact label keys must be reconciled with the pinned chart revision before they
are applied. `cloud-controller-1` retains its Kubernetes control-plane taint;
OpenStack control pods therefore require intentional tolerations.

The `openstack-cinder-volume` and `openstack-object-storage` labels are site
selectors rather than upstream defaults. The site Cinder and Swift values map
their storage workloads to these labels so that the default
`openstack-control-plane` selector does not place storage daemons on
`cloud-controller-1`.

## Service Placement

| Service class | Placement |
| --- | --- |
| Stateless OpenStack APIs | Both controllers |
| MariaDB and RabbitMQ | Three failure domains; design pending |
| OVN NB/SB databases | Three failure domains; design pending |
| OVN controller and OVS | Every compute node and both initial gateway nodes |
| Nova compute and libvirt | `cloud-controller-0` initially |
| Cinder volume service | `cloud-controller-0` only |
| Swift object-storage daemons | `cloud-controller-0` only |
| Provider gateway | Both controllers initially; every future compute is provider-connected and gateway-eligible |
| BIND DNS | Existing service on `cloud-controller-0`; redundancy pending |

## API Exposure

The preferred model follows current OpenStack-Helm guidance:

- Gateway API resources for HTTP(S) routing
- A supported Gateway API controller
- A Kubernetes LoadBalancer implementation suitable for bare metal
- DNS records targeting a dedicated API VIP
- TLS certificates and secrets managed outside Git

The API VIP must not reuse a node management address.

## Dependency Order

1. Kubernetes and host prerequisites
2. Persistent storage
3. Gateway API, load balancer, certificates, and DNS
4. MariaDB, RabbitMQ, and Memcached
5. Keystone
6. Glance and Cinder
7. Placement
8. OVS/OVN and Neutron
9. Libvirt and Nova
10. Horizon
11. Optional services
