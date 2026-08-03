# Network interface operations

Use the Grafana dashboard `VPC Control Plane / Network Interfaces` for ENI
attachment latency, Nova/Neutron convergence, orphan inventory, drift and Port
quota. The Horizon administrator panel is the source for per-ENI subnet address
capacity and audited operator actions.

## Capacity alerts

- `VPCNetworkInterfacePortQuotaLow` means ten or fewer Neutron Port slots remain.
- `VPCNetworkInterfacePortQuotaExhausted` means no additional ENI Port can be
  allocated. Check the project quota and remove only confirmed unused Ports.
- A Horizon `subnet-addresses-exhausted` reason is independent of the project
  Port quota: expand the subnet/VPC design or select another subnet.
- `VPCSubnetIPAddressCapacityLow` warns at ten available addresses.
- `VPCSubnetIPAddressExhaustionPredicted` uses six hours of allocation history
  and warns when linear growth reaches the subnet total within 24 hours. Treat
  it as planning evidence rather than an automatic resize instruction.

## Audit retention

The facade emits one structured `VPC ENI audit event` for every ENI mutation,
including user/project/request IDs but never tokens or request bodies. Promtail
sends these records to Loki, so they remain queryable after the CR is deleted.
The Grafana durable-audit panel is the primary operator view; CR annotations are
only the bounded, low-latency copy used by the facade audit API.
The reproducible Loki overlay sets retention to 30 days:

```sh
helm upgrade loki grafana/loki --namespace monitoring --version 7.1.0 \
  --reuse-values -f deploy/monitoring/values/loki-retention.yaml
```

## Orphan response

1. Confirm the Port appears in the operator inventory and has no Nova, router,
   Octavia or other Neutron owner.
2. Approve **quarantine** first. The controller re-fetches the Port and disables
   it only if it is still unused and not owned by any NetworkInterface CR.
3. Observe `admin_state_up=false`, then separately approve **delete**.
4. Use the Horizon ENI audit table and request ID to correlate the action with
   controller logs. Never delete a Port directly from an orphan alert alone.
