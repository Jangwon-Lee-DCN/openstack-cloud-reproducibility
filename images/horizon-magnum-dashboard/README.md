# Horizon Magnum UI

The production Horizon image includes the official OpenStack 2026.1
`magnum-ui` 18.0.0 plugin with `python-magnumclient` 4.10.0 and
`python-heatclient` 5.1.0. All three release wheels are checksum-verified.

The upstream plugin still references Bootstrap's `$gray-lighter` variable in
its cluster SCSS. Horizon's compressor does not expose that variable in every
active theme context, so startup fails with an undefined-variable error. The
image replaces the variable with its upstream Bootstrap value (`#eeeeee`).

The image then applies a fail-closed UI overlay for this platform's Magnum
CAPI/GitOps driver. The overlay keeps the public Magnum request schema intact,
but presents the actual lifecycle (Magnum -> rendered Git package -> Argo CD ->
CAPI/CAPO -> Nova/Neutron/Octavia), adds a final request review, selects the
supported load-balanced endpoint by default, and replaces legacy Heat-oriented
output with workload access, capacity, health, effective labels and reconcile
state. `enhance_magnum_ui.py` asserts every upstream replacement count so an
upstream wheel change cannot silently produce a partially patched dashboard.

Registered panels:

- Project > Container Infra > Clusters
- Project > Container Infra > Cluster Templates
- Admin > Container Infra > Quotas

The cluster creation defaults are one control plane and one worker, matching
the documented acceptance topology. The Octavia API load balancer and its
floating IP are selected by default. Production users must restrict the API
CIDRs and should use three control-plane nodes across three failure domains.

`images/horizon-complete/Dockerfile` contains the empty-Harbor build path.
`images/horizon-magnum-dashboard/Dockerfile` is the incremental production
layer used to preserve an already accepted cumulative Horizon image.
