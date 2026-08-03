# Horizon Magnum UI

The production Horizon image includes the official OpenStack 2026.1
`magnum-ui` 18.0.0 plugin with `python-magnumclient` 4.10.0 and
`python-heatclient` 5.1.0. All three release wheels are checksum-verified.

The upstream plugin still references Bootstrap's `$gray-lighter` variable in
its cluster SCSS. Horizon's compressor does not expose that variable in every
active theme context, so startup fails with an undefined-variable error. The
image replaces the variable with its upstream Bootstrap value (`#eeeeee`).
No Python or API behavior is forked.

Registered panels:

- Project > Container Infra > Clusters
- Project > Container Infra > Cluster Templates
- Admin > Container Infra > Quotas

`images/horizon-complete/Dockerfile` contains the empty-Harbor build path.
`images/horizon-magnum-dashboard/Dockerfile` is the incremental production
layer used to preserve an already accepted cumulative Horizon image.
