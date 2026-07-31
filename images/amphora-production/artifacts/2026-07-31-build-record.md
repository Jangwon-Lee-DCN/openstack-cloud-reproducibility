# Amphora Production Image Build Record — 2026-07-31

## Artifact identity

- File: `amphora-x64-haproxy-ubuntu-noble-2026.1.qcow2`
- Virtual size: 2 GiB
- File size: 377,606,656 bytes
- SHA-256: `1457ef64ba2e0603780b9e2ca3808f895afc9a11babb6371ef9fef2f8fe1be79`
- MD5: `d570bcc49b2177be66fc5d4c263e0cff`
- `qemu-img check`: no errors

## Guest inspection

- Distribution: Ubuntu 24.04 Noble
- HAProxy: 2.8.16
- Keepalived: 2.2.8
- Amphora agent: installed from pinned Octavia commit and enabled with
  `Restart=always`
- Cloud-init datasource: ConfigDrive only
- Root password: locked
- `openssh-server`: absent
- SSH boot unit: absent

## Glance record

- Image ID: `1b77ad93-c477-4ba7-8098-f5215978dc01`
- Name: `amphora-x64-haproxy-ubuntu-noble-2026.1-20260731`
- Owner: `b47511a2e2db40aaada92e722cafea51`
- Visibility: private
- Backend: RBD
- Glance checksum: `d570bcc49b2177be66fc5d4c263e0cff`
- Selection tag: `amphora`

The image and Amphora compute resources were subsequently moved to the
Octavia service project. Requesting tenants own the Octavia API objects but do
not own or see the implementation servers in their Nova server lists.

## Live acceptance test

An ACTIVE_STANDBY Amphora load balancer was created with two backends and a
floating IP. The load balancer reached `ACTIVE/ONLINE`, and both Amphora Nova
instances used the image ID above. Round-robin HTTP requests alternated between
`backend-1` and `backend-2`.

A controlled MASTER Amphora failover completed in approximately 50 seconds.
All 60 HTTP probes made at two-second intervals succeeded during the operation,
and Octavia returned to `ACTIVE/ONLINE` with a new MASTER/BACKUP pair.

The first failover attempt correctly exposed an operational prerequisite: Nova
was at its 10-instance quota and could not create the replacement before
deleting the old Amphora. The test was repeated with temporary headroom and
passed. The Nova quota was restored to 10 instances, 20 cores, and 51,200 MiB
RAM after the disposable test load balancer was removed.

## Cleanup

The disposable validation load balancer and floating IP were deleted. The
pre-existing `amphora-e2e-lb` was not modified. The former upstream test-only
image remains private with tag `amphora-test-only-retired` for rollback, but is
no longer selected for new Amphorae.
