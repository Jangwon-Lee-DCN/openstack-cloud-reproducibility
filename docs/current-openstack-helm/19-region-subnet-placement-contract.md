# Region and automatic rack placement contract

The tenant product surface follows an AWS-style hierarchy: choose the Region,
then a VPC and Subnet. Rack Availability Zone (AZ) is retained as an internal
failure-domain and scheduling result; users must not repeat it in each ordinary
create form.

```text
Region/service catalog
  -> VPC
     -> Subnet (automatic rack assignment when created)
        -> Nova/Cinder scheduling
        -> OVN/Neutron ports
        -> rack-local public network for north-south services
```

| Creation path | User selects | Platform resolves |
|---|---|---|
| Nova instance | Region, VPC, Subnet | Nova AZ from Subnet |
| Attached boot/data volume | instance | volume placement compatible with instance |
| Independent Cinder volume | Region; optional target context | explicit AZ is advanced-only because an unattached volume has no Subnet |
| ENI/port | Subnet | network and rack contract from Subnet |
| NAT gateway | public Subnet | matching rack public network |
| Elastic IP | association target/pool | target's rack-compatible public pool |
| Octavia load balancer | VIP Subnet | provider placement from VIP network; no raw AZ create selector |
| Magnum cluster | profile and existing/new cluster network | network AZ hint, otherwise stable automatic rack; same rack for CAPO and API public path |
| Ironic bare metal | role/network/traits | physical rack is inventory, not a generic tenant AZ selector |

Raw AZ remains visible in operator inventory, diagnostics and resource detail
pages. It remains an explicit advanced input only where no network or target
exists to infer placement, principally an independently created Cinder volume.
Region is not substituted into an OpenStack AZ field: it selects catalog
endpoints, while controllers translate the selected Subnet/target into the
service-specific AZ internally.

## Guardrails

- A selected network with more than one approved rack AZ hint is rejected as
  ambiguous.
- Rack-local external network, floating-IP/LB path and compute failure domain
  are resolved as one placement decision.
- Retries must return the same decision; Magnum's fallback hashes the immutable
  cluster UUID rather than making a fresh random choice.
- Operator/API compatibility fields may remain in backend schemas even when
  removed from ordinary Horizon forms.
