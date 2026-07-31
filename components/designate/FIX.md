# FIX: Designate and PowerDNS Deployment

The patched charts:

- render control-plane tolerations for all Designate services and PowerDNS;
- remove the circular bootstrap hook annotations;
- mount the pool configuration into central;
- embed a small WSGI entry point for the Designate API image;
- correct the service-cleaner volume reference;
- support host networking for mDNS and worker;
- run PowerDNS 4.9.16 unprivileged on port 5353;
- remove obsolete PowerDNS options and use current secondary-zone terminology;
- add Pod security context and replica anti-affinity support.

Site values register the stable per-node Cilium router addresses as mDNS
primaries and use `192.168.21.9:53` as the authoritative DNS target.

The Horizon image adds the official `designate-dashboard` 22.0.0 wheel above
the immutable image containing the existing Octavia and VPC panels. Its wheel
SHA-256 and final OCI image digest are pinned.

Patched packages are stored at:

- `helm/packages/patched/designate-2026.1.0.tgz`
- `helm/packages/patched/powerdns-2026.1.0.tgz`

The matching unmodified packages are retained under
`helm/packages/upstream/`.
