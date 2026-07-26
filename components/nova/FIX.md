# FIX: Explicit Ceph Replication Confirmation

The Nova storage initialization template adds `--yes-i-really-mean-it` when
setting the RBD pool size. This is required only because the PoC intentionally
uses a non-production replication size. The patched package is stored at
`helm/packages/patched/nova-2026.1.0.tgz`.
