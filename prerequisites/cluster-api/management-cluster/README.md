# CAPI/CAPO Management Controllers

The host Kubernetes cluster is the Cluster API management cluster used by
Magnum. Workload clusters are created as Nova VMs; they are not nested in the
host cluster.

Pinned components:

- Cluster API core, kubeadm bootstrap and kubeadm control plane: `v1.13.4`
- Cluster API Provider OpenStack: `v0.14.6`
- OpenStack Resource Controller (required by CAPO): `v2.5.0`
- Existing cert-manager: reused; the upstream manifests do not install another
  cert-manager release

All five controller deployments use two replicas, leader election, required
cross-node anti-affinity and a PDB with `minAvailable: 1`. This protects
controller process availability, but it does not remove the documented
two-member host-etcd quorum limitation.

Install:

```bash
./scripts/install.sh
```

The files under `vendor/` are unmodified upstream release assets. Site HA
changes are isolated in `overlays/poc-ha`. `scripts/render.py` performs the
same `${NAME:=default}` substitution that `clusterctl` applies to release
manifests; installing raw upstream YAML directly is unsupported.

The pinned ORC manifest has SHA-256
`99bf24f0472017585ff1a2df25c1584704fe5503575a711082608517e7fc77f2`.
ORC must be available before CAPO can start controllers that watch
`Image.openstack.k-orc.cloud`.
