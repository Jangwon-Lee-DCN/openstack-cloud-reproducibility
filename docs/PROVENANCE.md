# Upstream Provenance

## OpenStack-Helm

- Repository: `https://opendev.org/openstack/openstack-helm.git`
- Tag: `2026.1.0`
- Commit: `c665eed`
- Imported charts: every chart listed in `release-lock.yaml`, plus `gnocchi`
  and their shared `helm-toolkit` dependency

The chart trees were exported directly from the Git object at that commit.
They were not copied from the dirty deployment worktree. Chart dependencies
were built and the resulting packages were stored under
`helm/packages/upstream`.

## Image baselines

Image baseline files record either an immutable OCI digest or the upstream
language-package/base-image combination. Local Dockerfiles are introduced in
a later commit so that `git log` and `git diff` show the correction explicitly.
