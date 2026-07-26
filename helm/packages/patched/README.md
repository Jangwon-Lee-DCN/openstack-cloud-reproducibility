# Patched Helm Packages

These packages are the chart-source variants actually used by the PoC:

- `ironic-2026.1.0.tgz`: toleration indentation correction
- `nova-2026.1.0.tgz`: explicit Ceph replication-size confirmation
- `ovn-2026.1.0.tgz`: control-plane tolerations and pod-local OVSDB sockets

`SHA256SUMS` is authoritative. Every patch is a dedicated Git commit above the
clean upstream source and has a component ISSUE/FIX record. All other releases
use packages from `helm/packages/upstream`.
