# VM-Routable OpenStack Internal API Gateway

This Gateway exposes only OpenStack service APIs required by cloud workloads
and Cluster API nodes. It is separate from both the public cloud-user Gateway
and the Kubernetes platform-management Gateway.

- Gateway: `openstack-internal-gateway-system/openstack-internal-gateway`
- VIP: `192.168.21.7` announced on the `eno1` L2 network
- Origin: `https://api.internal.cloud.dcn.ssu.ac.kr`
- Route namespace: `openstack`
- Intended clients: CAPO, Magnum and Nova tenant VMs routed through Neutron
- Not exposed: dashboards, RabbitMQ, databases, metrics or Kubernetes APIs

The VIP is outside the Neutron external allocation pool
`192.168.21.100-192.168.21.200`. Tenant VMs reach it through their Neutron
router. The temporary PoC CA must be injected into workload-cluster images and
OpenStack `clouds.yaml`; production must replace it with institutional PKI.

Install and verify:

```bash
./scripts/install-bind-records.sh
./scripts/install.sh
./scripts/reconcile-catalog.sh
```

The catalog reconciler creates a child region named `RegionOne-VM`. Existing
`RegionOne/internal` ClusterIP endpoints remain unchanged so OpenStack service
Pods are not forced to trust the temporary VM-facing CA. Magnum-generated
workload credentials must select `RegionOne-VM` and include
`openstack-internal-ca`.

After DNS is configured, publish the service-catalog `internal` URLs using the
paths documented in `docs/endpoints.md`.

The route set intentionally includes both the canonical `/identity/v3` path
and Keystone's native `/v3` path. Do not remove the latter: Horizon's Nova
client and other generic `keystoneauth` consumers use it when re-scoping a
token even though the service catalog advertises the former.
Nova's native `/v2.1` path is retained for the same reason during microversion
discovery; the canonical catalog endpoint remains `/compute/v2.1`.
