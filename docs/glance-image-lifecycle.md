# Glance image lifecycle

The declared catalogue in `deploy/image-catalog/catalog.yaml` is authoritative
for supported tenant and service images. Phase 50 reconciles metadata,
visibility, hidden state, tags and deletion protection, then installs an hourly
read-only drift audit.

## User catalogue

- Supported Ubuntu general-purpose and CAPI images appear in Horizon.
- CAPI images remain public, visible and protected so project users can build
  their own CAPI clusters.
- Horizon keeps image names unchanged. Selecting one row opens a lower
  inspector with tags, a support-status badge, major image properties, and
  project-scoped linked Nova instances or CAPI clusters.
- The Amphora image remains private, hidden and owned by the service project.
- All managed images carry class, workload type, support status and OS version.

## Security and supply chain

Glance delete and modify rules require image ownership even when a project user
has the `admin` role. Only the cloud admin project can publish an image. Audit
middleware emits CADF notifications for API changes.

New images use `deploy/scripts/import-verified-glance-image.sh`. It requires
HTTPS, pinned SHA-256, a valid QCOW2 check, a non-empty CycloneDX SBOM and zero
critical vulnerability findings. Images start private and protected.

`glance-image-freshness-audit` runs every Monday and fails when a managed image
is older than 45 days or lacks its pinned source SHA-256. A failed audit starts
the verified import, Nova/CAPI/Octavia acceptance and explicit catalogue
promotion workflow; it never replaces a protected production image in place.

Before publication, `deploy/scripts/smoke-test-glance-image.sh` must observe an
ACTIVE Nova server and a cloud-init console marker. CAPI images additionally
require the existing Magnum/CAPO cluster create-delete acceptance, and Amphora
images require Octavia ACTIVE_STANDBY listener and failover acceptance.

## Backup, monitoring and recovery

`glance-image-backup` creates a daily PowerStore VolumeSnapshot and retains
seven generations. The hourly audit detects missing images, metadata drift,
missing tags and duplicate checksums. Prometheus alerts and the
`OpenStack / Glance Image Lifecycle` dashboard report failures and staleness.

`deploy/scripts/drill-glance-image-restore.sh` restores the latest snapshot into
a temporary PVC, mounts it read-only and compares every active image UUID and
SHA-512 before deleting only the temporary volume. It never mounts or replaces
the live PVC.

## Known infrastructure gate

Glance stores about 21 GiB on a 100 GiB PowerStore RWO PVC. The CSI node plugin
exists only on Compute nodes, so the API remains one replica on Compute. Moving
it to three `controller-1` nodes requires reviewed CSI/storage connectivity or
an HA backend migration. That work is excluded with switch changes and the
`dcn-1a-controller-1` incident and must not be reported as complete.

## Rollback

Revert the catalogue commit and rerun Phase 50. Removing protection remains
separately gated by `APPROVE_GLANCE_IMAGE_UNPROTECT=yes`.
