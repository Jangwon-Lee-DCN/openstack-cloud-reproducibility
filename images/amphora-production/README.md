# Production Amphora Image for OpenStack 2026.1

This directory builds the site Amphora image from pinned OpenStack sources.
It replaces the upstream `test-only` image used during the initial PoC.

## Pinned inputs

- Octavia stable/2026.1 commit:
  `50316329bea5ca55b3db9841bf2f804b97247872`
- diskimage-builder 3.40.2 commit:
  `aff6751d052a08a2ee084195e7024f8c5d282a42`
- requirements stable/2026.1 commit:
  `06cd4e8523cbade25fb93efc4f8ea77d6d97064f`
- Base distribution: Ubuntu Noble `ubuntu-minimal`, amd64
- Backend: HAProxy
- Output: 2 GiB qcow2
- Cloud-init datasource: ConfigDrive only
- SSH daemon: disabled
- Root account: disabled by the upstream default

The Ubuntu package mirror remains a time-dependent input. The output checksum,
installed package inventory, build timestamp, and Glance checksum must be
captured for every build. A production rebuild therefore produces a new image
version rather than pretending to be bit-for-bit identical.

## Build

```bash
./install-build-dependencies.sh
./build.sh
```

The default output directory is `/home/ubuntu/amphora-build-output`; the large
qcow2 file is deliberately not committed to Git. The build log, qemu metadata,
SHA-256 manifest, and Glance image metadata are recorded under `artifacts/`.

Validate the image locally before upload:

```bash
./verify-image.sh
```

Upload it under a candidate tag, then promote it only after inspection:

```bash
./upload-to-glance.sh
openstack image unset --tag amphora <previous-image-id>
openstack image set --tag amphora-test-only-retired <previous-image-id>
openstack image set --tag amphora <candidate-image-id>
openstack image unset --tag amphora-candidate <candidate-image-id>
```

The Nova project quota must have room for one temporary replacement instance
during an Amphora failover. An ACTIVE_STANDBY load balancer normally consumes
two instances, and replacing one creates the successor before deleting the old
instance.

## Security decisions

- No root password is injected.
- SSH is disabled; Octavia communicates with the Amphora agent over its mTLS
  management API.
- The image is private in Glance and owned by the Octavia service project.
- Amphora compute resources are created with `octavia@service` credentials in
  the service project, never in the requesting tenant project.
- Image selection uses the `amphora` tag and the configured owner ID.
- Existing Amphorae are not silently replaced. Rotate them with controlled
  failover after a new image passes an ACTIVE_STANDBY traffic test.

## Accepted build

The first accepted build and its live verification are recorded in
`artifacts/2026-07-31-build-record.md`. The Glance object remains private and
is selected by the `amphora` tag plus the configured owner ID.
