# Complete Horizon image

This directory is the authoritative, empty-registry build definition for the
Horizon image used by the cloud. It starts from the digest-pinned OpenStack
2026.1 Horizon image and installs every dashboard in one deterministic layer.

## OpenStack 2026.1 dashboard set

| Capability | Source | Version | Exposure |
| --- | --- | --- | --- |
| Load balancing | `octavia-dashboard` | 17.0.0 | Project users |
| DNS | `designate-dashboard` | 22.0.0 | Project users |
| Kubernetes | `magnum-ui` | 18.0.0 | Project users |
| Shared file systems | `manila-ui` | 15.0.0 | Project and admin panels |
| Instance HA | `masakari-dashboard` | 14.0.0 | Admin only |
| Block storage backup | Horizon built-in | Horizon 25.7.x | Project users |
| VPC and project IAM | Local locked projects | repository lock | Persona policy |

All remote wheels are downloaded from `tarballs.openstack.org` and checked
against an explicit SHA-256 digest before extraction. The Manila client is
also pinned because it is not part of the upstream Horizon runtime image.

Masakari remains an operator view. Installing its dashboard does not make
instance recovery safe: monitors and recovery actions must remain disabled
until compute fencing is available. Manila project actions remain governed by
the Manila service policy and project-scoped token.

## Verification

The Dockerfile fails the build unless each Python module imports and its panel
registration exists. After rollout, verify panel discovery in both Horizon
replicas and test with an ordinary project member as well as a cloud admin.
The ordinary member must not see the Masakari panel.

The Cinder Backups panel is supplied by Horizon itself and is enabled through
`deploy/values/site/horizon.yaml`:

```yaml
openstack_cinder_features:
  enable_backup: true
```

This UI switch is intentionally paired with the separately reconciled and
acceptance-tested Cinder backup service; it is not a substitute for it.
