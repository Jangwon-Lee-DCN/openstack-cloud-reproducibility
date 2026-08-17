# Glance image lifecycle

The declared catalogue in `deploy/image-catalog/catalog.yaml` is authoritative
for supported tenant and service images. Phase 50 reconciles metadata,
visibility, hidden state, tags and deletion protection, then installs an hourly
read-only drift audit.

## User catalogue

- Only supported Ubuntu general-purpose images appear in Horizon.
- CAPI images remain public and bootable by ID but are hidden from the general
  VM image catalogue.
- The Amphora image remains private, hidden and owned by the service project.
- All managed images carry class, workload type, support status and OS version.

## Security and supply chain

Glance delete and modify rules require image ownership even when a project user
has the `admin` role. Only the cloud admin project can publish an image. Audit
middleware emits CADF notifications for API changes.

New images use `deploy/scripts/import-verified-glance-image.sh`. It requires
HTTPS, pinned SHA-256, a valid QCOW2 check, a non-empty CycloneDX SBOM and zero
critical vulnerability findings. Images start private and protected.

Before publication, `deploy/scripts/smoke-test-glance-image.sh` must observe an
ACTIVE Nova server and a cloud-init console marker. CAPI images additionally
require the existing Magnum/CAPO cluster create-delete acceptance, and Amphora
images require Octavia ACTIVE_STANDBY listener and failover acceptance.

## Backup, monitoring and recovery

`glance-image-backup` creates a daily PowerStore VolumeSnapshot and retains
seven generations. The hourly audit detects missing images, metadata drift,
missing tags and duplicate checksums. Prometheus alerts and the
`OpenStack / Glance Image Lifecycle` dashboard report failures and staleness.

A recovery drill restores a snapshot into a new PVC and compares every active
image UUID, size and checksum before cutover. Never restore over the live PVC.

## Known infrastructure gate

Glance stores about 21 GiB on a 100 GiB PowerStore RWO PVC. The CSI node plugin
exists only on Compute nodes, so the API remains one replica on Compute. Moving
it to three `controller-1` nodes requires reviewed CSI/storage connectivity or
an HA backend migration. That work is excluded with switch changes and the
`dcn-1a-controller-1` incident and must not be reported as complete.

## Rollback

Revert the catalogue commit and rerun Phase 50. Removing protection remains
separately gated by `APPROVE_GLANCE_IMAGE_UNPROTECT=yes`.
