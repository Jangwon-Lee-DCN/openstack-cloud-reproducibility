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

## Amphora extension symptoms and root causes

1. The Amphora worker could not resolve the image tagged `amphora` because TLS
   verification failed against the internal Glance endpoint.
2. Configuring a CA only under `[glance]` did not fix catalog-discovered
   endpoints. The Glance client used Octavia's shared Keystone session, which
   requires `[service_auth] cafile`.
3. The chart expected DHCP on the Amphora management interfaces, but the
   node-bound Neutron ports already had fixed addresses. The container could
   not open the required raw DHCP socket.
4. A chart-generated multi-host RabbitMQ URL was parsed incorrectly when the
   password contained URL delimiter characters.
5. Enabling Taskflow jobboard failed because the selected Airship Octavia image
   lacks the optional Python Redis client.
6. After publishing a custom image, worker Pods on the uncached controller
   failed with `unauthorized` because the upstream worker and health-manager
   DaemonSets did not render the configured image pull Secret.
7. Sentinel discovery failed authentication even though the Valkey credential
   was correctly configured. Octavia 2026.1/Taskflow intentionally does not
   pass data-store credentials to Sentinel connections.

These are persistent configuration or image defects. Waiting for all Octavia
Pods to become Ready does not resolve them.
