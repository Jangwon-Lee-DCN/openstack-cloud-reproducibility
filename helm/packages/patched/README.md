# Patched Helm Packages

These packages are the chart-source variants actually used by the PoC:

- `ironic-2026.1.0.tgz`: toleration indentation correction
- `nova-2026.1.0.tgz`: explicit Ceph replication-size confirmation
- `ovn-2026.1.0.tgz`: control-plane tolerations and pod-local OVSDB sockets
- `octavia-2026.1.0.tgz`: registry pull secrets, controller tolerations,
  Octavia service-project compute authentication, and
  node-local API/driver-agent socket sharing
- `horizon-2026.1.0.tgz`: registry pull secret support for the Octavia-enabled
  Horizon image
- `skyline-2026.1.0.tgz`: controller toleration and anti-affinity support
- `magnum-2026.1.0.tgz`: projected-token CAPI kubeconfig, registry pull
  secrets, and control-plane tolerations
- `designate-2026.1.0.tgz`: bootstrap dependency fixes, pool/WSGI mounts,
  control-plane tolerations, and host-networked DNS control traffic
- `powerdns-2026.1.0.tgz`: PowerDNS 4.9 compatibility, non-root execution,
  tolerations, anti-affinity, and security context

`SHA256SUMS` is authoritative. Every patch is a dedicated Git commit above the
clean upstream source and has a component ISSUE/FIX record. All other releases
use packages from `helm/packages/upstream`.
