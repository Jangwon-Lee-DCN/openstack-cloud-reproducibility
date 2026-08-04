# Capability Expansion Artifact Record

This artifact set freezes the charts and values used for the August 2026 cloud
capability expansion.

| Capability | Locked artifact | Material site change |
| --- | --- | --- |
| Manila/CephFS | `helm/packages/patched/manila-2026.1.0.tgz` | Removed 2026.1 reference to deleted `manila.api.v1`; site values select native CephFS and two-controller placement. |
| Cinder Backup | `helm/packages/patched/cinder-2026.1.0.tgz` | Two anti-affined single-process consumers advertise unique RPC hosts; the backup container is privileged so the Noble/2026.1 os-brick helper can attach RBD sources. |
| Telemetry | Existing locked Ceilometer, Gnocchi, and Aodh packages | Runtime reconciliation makes optional Nova flavor attributes match actual notification and poll payloads. |
| RGW S3 | Existing Rook-Ceph release | Gateway and DNS configuration is owned by `openstack-cloud-services`; RGW remains the same two-replica object store. |
| Masakari | `helm/packages/patched/masakari-2026.1.0.tgz` | API/engine tolerate the controller taint and spread across both controllers; monitors remain disabled. |

The release lock points Cinder, Manila, and Masakari to the patched packages
and separates non-secret site values from SOPS-encrypted credentials. Verify
the package hashes before deployment:

```bash
cd helm/packages/patched
sha256sum -c SHA256SUMS
```

Masakari monitor activation is intentionally not part of this artifact set.
It requires redundant compute capacity and tested fencing in the production
datacenter topology.
