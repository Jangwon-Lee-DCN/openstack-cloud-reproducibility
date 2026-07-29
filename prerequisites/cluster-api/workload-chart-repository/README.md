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

The installer rejects an index that points at the retired
`magnum-workload-chart-repository.capi-system` service. Repackage the chart and
regenerate `index.yaml` with:

```bash
helm repo index helm/repositories/magnum-workload \
  --url http://magnum-chart-repository.openstack.svc.cluster.local
```
