# Least-Privilege OpenStack Monitoring RBAC

## Reproduced security model

OpenStack Exporter 1.7.0 authenticates as
`prometheus-openstack-exporter` in the `service` project with the dedicated
project-scoped `monitoring` role. The site values grant only collector reads
and preserve administrator access with:

```text
role:admin or role:monitoring
```

The committed policy overrides cover Keystone inventory; Nova service,
capacity, hypervisor, and server reads; Cinder service, pool, quota, volume,
and snapshot reads; Placement provider inventory and usage; and Octavia
amphora inventory. No create, update, or delete rule grants the `monitoring`
role.

Unsupported or absent service collectors and known incompatible metrics are
disabled explicitly in `deploy/monitoring/values/openstack-exporter.yaml`.
Cinder service-state and scheduler-pool collectors are disabled because
Cinder additionally requires an internal administrator context after policy
evaluation; the exporter is not granted `admin` to bypass that check.

The PoC Gateway certificate is self-signed. The pinned chart supports the
explicit `verify` setting and this deployment sets it to `false`. Replace that
setting with a trusted CA bundle and enable verification for production.

## Reconcile requirements

Always pass both `deploy/values/site/<service>.yaml` and the matching
SOPS-decrypted `deploy/secrets/<service>.values.sops.yaml` to Helm. Omitting
the encrypted values can replace a service credential with a chart-generated
default.

For the single-replica Cinder PoC, a rolling upgrade may wait on
`post-upgrade` Jobs while the Jobs wait behind workload readiness. Render and
apply the Cinder initialization and Keystone Jobs to the `openstack`
namespace, wait for completion, and reconcile the release with
`helm upgrade --no-hooks --wait`. This procedure must not delete databases,
PVCs, volumes, or Ceph data.

## Acceptance criteria

- The exporter user has only the `monitoring` role in `service`.
- All committed monitoring rules are reads and retain `role:admin`.
- Both exporter replicas are ready.
- One full 60-second collection cycle has no authorization or collector
  errors.
- The Prometheus target for the exporter is up.
