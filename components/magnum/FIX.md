# FIX

- Build from the pinned Airship Magnum digest and install
  `magnum-capi-helm==1.4.0` plus Helm `3.18.4`.
- Patch the driver to reread a projected ServiceAccount `tokenFile` and to
  generate workload credentials against the `RegionOne-VM` internal endpoint.
- Add the missing WSGI entry point.
- Patch the chart for CA/token file kubeconfig fields, registry pull secrets,
  and control-plane tolerations.
- Configure two API and two conductor replicas, required cross-node
  anti-affinity, and PDB `minAvailable: 1`.
- Override the Paste pipeline to omit the incompatible healthcheck filter.

The deployed image is pinned as:

`registry.dcn.ssu.ac.kr/openstack/magnum@sha256:77e12d055cc88349241addd39750233d14ba493717a44681f90015d91aa7b683`
