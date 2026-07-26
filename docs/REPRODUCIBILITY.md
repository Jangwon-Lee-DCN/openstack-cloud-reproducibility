# Reproducibility Model

## Commit layers

- `4c3a128`: untouched OpenStack-Helm 2026.1.0 source and packages
- the next commit: deployment-specific image, values, manifest, and Secret
  corrections
- later commits: deterministic hardening and executable runbooks

Use `git diff 4c3a128..HEAD` to inspect every local addition. The upstream
chart trees should remain unchanged unless a chart source patch is necessary.
Such a patch must be a dedicated commit and a package must also be written to
`helm/packages/patched` with checksums.

## Determinism boundaries

OCI base images are pinned by digest. Application versions are pinned in the
Dockerfiles and runtime images are pinned in values/manifests. Debian APT and
Python package transitive dependencies are not yet locked by snapshot and hash,
so byte-for-byte image rebuild reproducibility is not claimed. A rebuilt image
must be reviewed by digest before deployment.

SOPS files under `deploy/secrets` are the current PoC environment profile.
They reproduce this environment but must be regenerated for another cloud.
