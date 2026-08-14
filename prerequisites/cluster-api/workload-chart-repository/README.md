# Magnum Workload Chart Repository

This internal, HA Nginx service publishes the locally patched
`openstack-cluster` workload chart to Magnum conductors.

The patch uses the unified production region:

- `seoul-ssu-1` is used by CAPO controllers in the management cluster and by
  CCM and CSI inside workload VMs.
- Workload VMs select the public interface, whose API gateway is routable and
  carries the public certificate chain. Management-cluster services may use
  the cluster-local internal interface in the same region.

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
