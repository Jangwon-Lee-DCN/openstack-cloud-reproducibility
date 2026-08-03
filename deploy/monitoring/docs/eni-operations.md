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

## Orphan response

1. Confirm the Port appears in the operator inventory and has no Nova, router,
   Octavia or other Neutron owner.
2. Approve **quarantine** first. The controller re-fetches the Port and disables
   it only if it is still unused and not owned by any NetworkInterface CR.
3. Observe `admin_state_up=false`, then separately approve **delete**.
4. Use the Horizon ENI audit table and request ID to correlate the action with
   controller logs. Never delete a Port directly from an orphan alert alone.
