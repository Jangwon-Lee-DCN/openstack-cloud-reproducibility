# Tenant Isolation for Amphora Compute Resources

The patched Octavia chart resolves `[service_auth]` from
`endpoints.identity.auth.octavia`, not the chart's admin credentials. This
causes Nova, Neutron, and Glance operations for Amphora appliances to run in
the Octavia service project.

Required cloud-side resources are also service-project scoped:

- private production Amphora image;
- Amphora management security group;
- RBAC access to the provider-owned management network.

The requesting tenant continues to own the load-balancer API object and VIP,
but not the implementation VM. This is an authorization boundary rather than
a Horizon/Skyline display filter.

Nova must retain its default project-reader policy for
`os_compute_api:servers:detail`. Only the `get_all_tenants` variant is reserved
for admin and monitoring roles.
