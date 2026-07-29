# Magnum Workload Chart Repository

This internal, HA Nginx service publishes the locally patched
`openstack-cluster` workload chart to Magnum conductors.

The patch separates two region selections:

- `RegionOne` is used by CAPO controllers running in the management cluster.
- `RegionOne-VM` remains in `clouds.yaml` for CCM and CSI running inside
  workload VMs, where the routable API gateway is required.

Install with:

```bash
./scripts/install.sh
```

