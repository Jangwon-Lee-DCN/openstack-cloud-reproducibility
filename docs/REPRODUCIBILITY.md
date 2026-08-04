# Reproducibility Model

## Change layers

The current `main` branch, `release-lock.yaml`, SOPS release snapshots and
digest-pinned image values together define the accepted deployment. Do not use
old documentation commit IDs as rebuild inputs: record and bundle the exact
commit selected for each new installation.

Upstream chart trees should remain unchanged unless a chart source patch is
necessary. Such a patch must be a dedicated commit, be represented in the
locked package/checksum inventory, and have a render or runtime regression
test. Use `git log --reverse` and the component records when auditing how the
current state differs from the imported upstream baseline.

## Determinism boundaries

OCI base images are pinned by digest. Application versions are pinned in the
Dockerfiles and runtime images are pinned in values/manifests. Debian APT and
Python package transitive dependencies are not yet locked by snapshot and hash,
so byte-for-byte image rebuild reproducibility is not claimed. A rebuilt image
must be reviewed by digest before deployment.

SOPS files under `deploy/secrets` are the current PoC environment profile.
They reproduce this environment but must be regenerated for another cloud.
