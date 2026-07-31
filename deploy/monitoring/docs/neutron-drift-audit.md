# Neutron drift audit

`scripts/audit-vpc-neutron-drift.sh` compares SecurityGroup, ElasticIP, and
NatGateway status IDs with real Neutron SG/FIP/router inventories. It detects
both CRs whose actual resource is missing and managed Neutron resources not
tracked by a CR.

Run it with project-scoped OpenStack credentials:

```sh
deploy/monitoring/scripts/audit-vpc-neutron-drift.sh project-<id> report.json
```

Set `PUSHGATEWAY_URL` to publish `vpc_neutron_drift_resources` for Grafana.
The auditor never mutates CRs or Neutron. Review its JSON and Kubernetes Events,
then use the normal controller retry path separately if correction is safe.
