# nova operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `nova`.

## Known issues and scope

Nova's storage initialization attempted to reduce a Ceph pool replication size
without the explicit confirmation required by Ceph. The Job failed in the
single-OSD PoC topology.

## Remediation

The Nova storage initialization template adds `--yes-i-really-mean-it` when
setting the RBD pool size. This is required only because the PoC intentionally
uses a non-production replication size. The patched package is stored at
`helm/packages/patched/nova-2026.1.0.tgz`.
