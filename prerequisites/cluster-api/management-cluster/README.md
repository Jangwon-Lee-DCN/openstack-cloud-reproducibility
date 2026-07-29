# CAPI/CAPO Management Controllers

The host Kubernetes cluster is the Cluster API management cluster used by
Magnum. Workload clusters are created as Nova VMs; they are not nested in the
host cluster.

Pinned components:

- Cluster API core, kubeadm bootstrap and kubeadm control plane: `v1.13.4`
- Cluster API Provider OpenStack: `v0.14.6`, with the pinned Neutron
  port-pagination compatibility image described below
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

The installer copies the existing Harbor pull secret into `capo-system`
without exposing its value and pins:

`registry.dcn.ssu.ac.kr/openstack/capo-controller@sha256:91bfcbad65adfacd832ec6935011eee76790ac71b27e9d333d125a7d519f4cf8`

`manifests/capo-image-build.yaml` records the reproducible build. It changes
the unique-port lookup limit from one to two to avoid an incompatible Neutron
pagination response. The unmodified source archive and standalone patch live
in `openstack-cloud-reproducibility/sources`.

The files under `vendor/` are unmodified upstream release assets. Site HA
changes are isolated in `overlays/poc-ha`. `scripts/render.py` performs the
same `${NAME:=default}` substitution that `clusterctl` applies to release
manifests; installing raw upstream YAML directly is unsupported.

The pinned ORC manifest has SHA-256
`99bf24f0472017585ff1a2df25c1584704fe5503575a711082608517e7fc77f2`.
ORC must be available before CAPO can start controllers that watch
`Image.openstack.k-orc.cloud`.
