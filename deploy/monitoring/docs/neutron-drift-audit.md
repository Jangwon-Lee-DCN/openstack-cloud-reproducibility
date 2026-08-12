# Neutron drift audit

The production path is a per-project CronJob installed by
`scripts/install-drift-auditor.sh`. It runs every 15 minutes and compares:

- Security Groups/rules, Floating IP association/fixed IP, Internet/NAT
  router gateways, Load Balancers, and VPC Endpoint Ports;
- `FlowLogConfig` against the Neutron log resource's target, event and enabled
  fields;
- `PrivateDnsZone` against its Designate Zone and all controller-owned
  recordsets, excluding Designate-managed SOA/NS;
- managed Network Interface Ports, including missing/orphaned `vpc-ni-*`
  Ports and ownership tags;
- controller ownership tags and controller-shaped resources that no CR tracks.

The controller continuously owns `vpc-control-plane` and
`vpc-cr-uid=<Kubernetes UID>` on tag-capable Neutron resources. User-facing
tags remain in the separate `dcn:<key>=<value>` namespace. A changed CR UID is
therefore replaced, rather than accumulated, on the next reconciliation.

```sh
deploy/monitoring/scripts/install-drift-auditor.sh vpc-<project-id> [...]
```

For an immediate audit, start a one-off Job from that same CronJob. The wrapper
waits for completion, saves the JSON log, and rejects a report missing any
production summary category; it does not use a reduced local comparison:

```sh
deploy/monitoring/scripts/audit-vpc-neutron-drift.sh \
  vpc-<project-id> /tmp/vpc-drift.json
```

Each Job uses only that namespace's project credential and read-only CRD RBAC.
It publishes `vpc_neutron_drift_resources` and a last-success timestamp for
Grafana/Prometheus. The auditor never mutates CRs or Neutron.

After reviewing the report, an operator can explicitly request a single
controller retry. There is no unattended repair loop:

```sh
APPROVE_RECONCILE=yes deploy/monitoring/scripts/request-drift-reconcile.sh \
  vpc-<project-id> securitygroup <name>
```

`VPCNeutronDriftPersistent` fires when drift lasts 30 minutes and
`VPCNeutronDriftAuditStale` fires when successful audits stop.

Existing untagged resources can be migrated one at a time with project-scoped
credentials after checking the CR UID:

```sh
APPROVE_TAG_CHANGE=yes deploy/monitoring/scripts/apply-vpc-ownership-tags.sh \
  security-group <neutron-id> <cr-uid>
```

This is intentionally not an unattended mutation. Replacement resources remain
visible as tag drift until their owning reconciler adopts the tag contract.
