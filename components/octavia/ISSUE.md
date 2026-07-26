# ISSUE: Octavia OVN Provider Integration

## Affected baseline

- OpenStack-Helm chart `2026.1.0`
- Octavia `18.0.1.dev3`
- OVN Octavia provider `10.0.0`
- Two-controller Kubernetes PoC

## Symptoms

1. The upstream Octavia image did not contain the complete OVN provider
   dependency set.
2. Provider initialization blocked when a single OVN DB ClusterIP selected a
   follower.
3. `/v2/lbaas/providers` returned an empty list after API startup.
4. LB creation failed with TLS verification against the self-signed public
   Neutron endpoint.
5. Initial Cirros backends did not receive metadata user data.
6. Public LB requests timed out while backend TCP/80 only allowed the tenant
   CIDR.

## Root causes

- The OVN provider is not complete in the selected base image.
- Clustered OVSDB clients need all NB/SB remotes for leader discovery.
- The chart isolates driver-agent Unix sockets in a Pod-local `emptyDir`;
  Octavia API therefore cannot reach `status.sock`.
- Octavia's Neutron client selects the public service catalog interface unless
  `neutron.valid_interfaces` is set.
- The PoC metadata data path did not deliver user data; config drive is an
  independent delivery mechanism.
- OVN preserves client source addresses, so tenant-only backend ingress does
  not admit public clients.
