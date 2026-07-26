# Network Design

## Interface Contract

### `eno1` — protected primary uplink

On both controllers, `eno1` provides:

- Administrative access
- The host default route and internet egress
- Kubernetes node and API connectivity
- Primary OpenStack management/API connectivity

No unattended procedure may detach `eno1`, remove its address, move its
default route, or enslave it to an OVS bridge.

### `eno2` — provider/data uplink

On compute-capable nodes, `eno2` is the physical uplink for `br-ex` or the
equivalent OVN provider bridge. `cloud-controller-0` currently has
`192.168.21.11/24` on `eno2`. The approved PoC target removes this host L3
address and attaches the addressless interface to `br-ex`. The change requires
local console access, a timed rollback, and pre/post connectivity tests.

`cloud-controller-1` is not initially a compute node, but it is an OVN gateway
chassis for external-path HA. Its current `192.168.21.13/24` host address is
removed and its addressless `eno2` is attached to `br-ex` using the same safe
migration procedure. Every future compute node follows this provider mapping.

## Logical Networks

| Network | Purpose | CIDR/VLAN | Status |
| --- | --- | --- | --- |
| Management | Host, Kubernetes, OpenStack control | `192.168.21.0/24` | Existing |
| Kubernetes Pods | Cilium pod traffic | `10.200.0.0/16` | Existing |
| Kubernetes Services | ClusterIP services | `10.96.0.0/12` | Existing |
| Tenant overlay | OVN Geneve over `eno1` | VPC-defined; transport `192.168.21.0/24` | PoC decision approved |
| Provider/external | Flat Floating IP and north-south traffic over `br-ex`/`eno2` | `192.168.21.0/24`, gateway `192.168.21.1`, pool `192.168.21.100-192.168.21.200` | PoC decision approved |
| Storage | Backend replication/client traffic | TBD | Design required |

All CIDRs must be non-overlapping.

## OVN/Provider Mapping

Approved PoC mapping:

```text
Neutron physical network: external
OVN/OVS bridge mapping:   external:br-ex
Physical uplink:          br-ex -> eno2
Tenant overlay:           Geneve
Geneve endpoint:          eno1 management address
External subnet:          192.168.21.0/24
External gateway:         192.168.21.1
Allocation pool:          192.168.21.100-192.168.21.200 (inclusive)
Distributed Floating IP:  enabled
Gateway chassis:          both controllers and every future compute
Provider presentation:    untagged; multiple source MAC addresses allowed
```

Only the external/provider network is flat. Tenant networks remain isolated
OVN logical datapaths carried by Geneve. MTU must account for Geneve overhead
and the existing Cilium overlay.

The inclusive range `192.168.21.100-192.168.21.200` is reserved exclusively
for Neutron router external ports and Floating IPs. It must be excluded from
upstream DHCP, static host assignments, Cilium LoadBalancer pools, and every
other address manager. A Neutron router gateway consumes an address from this
same pool, so not all 101 addresses are available as Floating IPs.

## VPC Isolation and CIDR Policy

- Independent VPCs use separate Neutron networks and routers and are isolated
  by default, including when their IPv4 CIDRs are identical or overlapping.
- Networks are private by default: no Neutron `shared` flag or cross-project
  RBAC grant is created implicitly.
- Subnets inside one VPC must not overlap.
- Peering is rejected if any IPv4 or IPv6 CIDR overlaps.
- Transit attachment is rejected if any attached VPC CIDR overlaps.
- Internet gateway attachment is represented by a Neutron router external
  gateway. Its external port and all Floating IPs are globally unique within
  the provider network; they do not come from the VPC CIDR.
- Routes and security policy must be explicitly reconciled before traffic is
  permitted between otherwise isolated networks.

This follows the AWS behavior at the product boundary: overlapping standalone
VPCs are allowed, while connections that require unambiguous private routing
reject overlap.

## Distributed North-South Behavior

Both controllers and every future compute receive `external:br-ex`, physical
provider connectivity through addressless `eno2`, and OVN gateway eligibility.
This gives router gateway ports multiple chassis for BFD-based failover.

Neutron `enable_distributed_floating_ip` is enabled. A VM with a Floating IP
uses DNAT/SNAT on its local compute and reaches the external network directly
through that compute's `br-ex`; it does not hairpin through another gateway.

A private VM without a Floating IP is different: standard ML2/OVN router SNAT
still traverses the active gateway chassis selected for its router. Making all
computes gateway-eligible distributes and narrows that failure domain, but does
not guarantee that ordinary SNAT is local to the VM's compute. A requirement
for strictly local north-south traffic must therefore assign a distributed
Floating IP or use a directly attached provider port; it must not assume that
default router SNAT is distributed.

## Required Decisions

- MTU for management, provider, and overlay paths
- IPv6 scope
- Final reviewed `eno2` migration command and timed rollback procedure
