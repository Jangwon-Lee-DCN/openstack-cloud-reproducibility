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

The deployed image is pinned as:

`registry.dcn.ssu.ac.kr/openstack/magnum@sha256:4eda7acd9b7eea0c66662917a29151e22118e8ac89859017cc84a3948c5b426a`
