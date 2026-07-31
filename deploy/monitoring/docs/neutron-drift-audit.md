# Neutron drift audit

The legacy `scripts/audit-vpc-neutron-drift.sh` remains useful for an ad-hoc
report. The production path is a per-project CronJob installed by
`scripts/install-drift-auditor.sh`. It runs every 15 minutes and compares:

- Security Group and rule IDs
- Floating IP existence, target port, and fixed IP
- NAT router existence, external network/fixed IPs, and `enable_snat`
- managed Neutron resources no longer tracked by a CR
- missing `vpc-control-plane` and `vpc-cr-uid=<uid>` ownership tags

```sh
deploy/monitoring/scripts/install-drift-auditor.sh vpc-<project-id> [...]
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
