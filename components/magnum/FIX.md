# FIX

- Build from the pinned Airship Magnum digest and install
  `magnum-capi-helm==1.4.0` plus Helm `3.18.4`.
- Patch the driver to reread a projected ServiceAccount `tokenFile`.
- Generate both `openstack` (`RegionOne-VM`, workload add-ons) and
  `openstack-capo` (`RegionOne`, management CAPO) cloud entries.
- Select `openstack-capo` for infrastructure resources while omitting the
  Machine identity region, keeping provider IDs canonical.
- Honor `master_lb_enabled`; no-LB remains an experimental PoC mode.
- Add the CCM bootstrap toleration and make hardware-specific add-ons opt-in.
- Add the missing WSGI entry point.
- Patch the chart for CA/token file kubeconfig fields, registry pull secrets,
  and control-plane tolerations.
- Configure two API and two conductor replicas, required cross-node
  anti-affinity, and PDB `minAvailable: 1`.
- Override the Paste pipeline to omit the incompatible healthcheck filter.
- Enable CCM-managed LoadBalancer security groups in the workload chart.
- Preserve optional legacy cluster and Machine cloud selections so existing
  clusters can roll to the split `openstack`/`openstack-capo` identity model.
- Generate the repository index with
  `http://magnum-chart-repository.openstack.svc.cluster.local`.
- Set the PoC project quota to at least 50 security groups and 500 rules.
- Reapply two replicas, required hostname anti-affinity, and a PDB after every
  ORC upgrade.
- Grant the Magnum conductor `deletecollection` in addition to `delete` for
  the management resources covered by its CAPI ClusterRole.

The deployed image is pinned as:

`registry.dcn.ssu.ac.kr/openstack/magnum@sha256:4eda7acd9b7eea0c66662917a29151e22118e8ac89859017cc84a3948c5b426a`
