# Neutron FWaaS v2 with ML2/OVN

## Deployed State

Neutron FWaaS v2 is enabled on the 2026.1 ML2/OVN deployment. It uses the
upstream `neutron-fwaas` 24.0.0 OVN service driver:

```ini
[DEFAULT]
service_plugins = ovn-router,firewall_v2

[service_providers]
service_provider = FIREWALL_V2:fwaas_db:neutron_fwaas.services.firewall.service_drivers.ovn.firewall_l3_driver.OVNFwaasDriver:default
```

This does not require a local OVN fork. The upstream driver translates FWaaS
v2 firewall groups and rules into OVN Northbound `Port_Group` and `ACL` rows.
The API remains FWaaS v2 rather than an AWS Network ACL API; the VPC control
plane must provide any NetworkAcl compatibility semantics and validation.

## Reproducible Artifacts

- `images/neutron-fwaas/Dockerfile` layers the released
  `neutron_fwaas-24.0.0` wheel onto the pinned Neutron 2026.1 image.
- `deploy/manifests/neutron-fwaas-image-build.yaml` builds the image with
  Kaniko and pushes it to the site registry.
- `deploy/values/site/neutron.yaml` selects the immutable image digest and
  enables the plugin and OVN driver.
- `helm/packages/patched/neutron-2026.1.0.tgz` explicitly runs the
  `neutron-fwaas` Alembic subproject during the Neutron DB sync hook.
- `deploy/manifests/neutron-harbor-serviceaccounts.yaml` supplies the private
  registry pull secret to Neutron API and DB migration workloads.

The image build ignores `/usr/bin/arping` because Kaniko cannot restore its
file capability xattr in this cluster. Neutron API and database migration
processes do not use that executable.

## Migration and Deployment

Before the first enablement, take a logical Neutron database backup. Build and
push the pinned image, then reconcile Neutron through the normal full-stack
script. The patched DB hook runs:

```text
neutron-db-manage --subproject neutron-fwaas upgrade head
```

The expected FWaaS tables include `firewall_groups_v2`,
`firewall_group_port_associations_v2`, `firewall_policies_v2`,
`firewall_policy_rule_associations_v2`, and `firewall_rules_v2`.

## Acceptance Record

Acceptance was completed on 2026-07-30:

1. Neutron advertised the `fwaas_v2` extension.
2. API calls created a firewall rule, policy, and firewall group.
3. The group attached to a `network:router_interface` port and reached
   `ACTIVE`.
4. OVN Northbound contained a `Port_Group` with
   `neutron:firewall_group_id` and six ACLs, including the requested IPv4
   allow rule and default IPv4/IPv6 drops.
5. Deleting the API resources removed the corresponding OVN port group.
6. The temporary network, subnet, router, and firewall resources were removed.

This proves that the upstream OVN driver programs the deployed backend. It
does not by itself prove full AWS Network ACL behavioral parity; ordering,
stateless behavior, IPv6, concurrent updates, quota policy, security-group
interaction, and dataplane allow/deny cases still require control-plane
contract tests.

## Rollback

Remove all firewall groups before disabling the plugin. Restore the prior
Neutron image and configuration through Helm. Database downgrades are not part
of the routine rollback path; preserve the pre-migration logical backup and
use it only under an approved database recovery procedure.
