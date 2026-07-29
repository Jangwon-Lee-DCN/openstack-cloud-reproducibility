# Cluster API Add-on Provider

The Magnum CAPI workload chart emits `HelmRelease` and `Manifests` resources
from `addons.stackhpc.com/v1alpha1`. The Cluster API add-on provider owns those
CRDs and installs bootstrap components such as Calico, OpenStack CCM, and
Cinder CSI into each workload cluster.

## PoC pin

- Chart: `cluster-api-addon-provider`
- Version: `0.12.1`
- Namespace: `capi-addon-system`
- Release: `capi-addons`
- Package source:
  `/home/ubuntu/openstack-cloud-reproducibility/helm/packages/upstream/`

The upstream controller intentionally uses one replica with a `Recreate`
strategy to avoid reconciliation races. This is an explicit HA exception:
Kubernetes restarts it on the surviving controller, while existing workload
clusters and their Kubernetes control planes continue operating independently.

## Install and verify

```bash
./scripts/install.sh
./scripts/verify.sh
```

