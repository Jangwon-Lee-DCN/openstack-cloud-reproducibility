# Track A integration requirements

Track A intentionally did not edit shared image-build, release, site values,
Horizon-complete or production reconciliation files. The integration owner must
later make the following reviewed changes after development acceptance:

1. Add a reproducible Kaniko/build job for `images/platform-core-orchestrator`
   and record the exact accepted digest without rebuilding for production.
2. Register `automation/development/components/p0-core-orchestration.sh` in the
   site delivery repository if components are not collected from locked child
   repositories.
3. Add PostgreSQL credentials through SOPS and a migration Job; never reuse the
   development SQLite volume. Implement the repository adapter using the
   committed `FOR UPDATE SKIP LOCKED` claim/outbox statements and test failover.
4. Configure the implemented direct boundary with
   `CORE_AUTH_MODE=keystone-opa`, an internal Keystone v3 URL, and the
   `vpc/authz/decision` OPA URL. It validates `X-Auth-Token`, requires project
   scope, derives identity/roles only from Keystone, and fails closed on an OPA
   deny or outage. Development identity headers are forbidden in this mode.
5. Add a numeric production Phase that defaults all three feature flags off,
   performs check/diff, deploys three API replicas and multiple workers, and
   runs acceptance before any flag is enabled.
6. Compose the independent Horizon dashboard overlay only after the OpenAPI and
   error contracts are reviewed with all tracks.

Required Track B/C interfaces are the versioned outbox topics
`operation.requested.v1`, `operation.cancelled.v1`,
`resource.protection.changed.v1` and `recycle-bin.retained.v1`. Consumers are
at-least-once and must deduplicate by outbox ID/aggregate ID; delivery failure
must never roll back provider reconciliation.

## Real-provider development evidence (2026-08-16)

From `development-p0-core-orchestration` on `dcn-1b-utility-0`, a development
NetworkPolicy allowed only the `openstack` namespace on Keystone, Nova,
Neutron, Cinder, Placement, Octavia and Aodh API ports, plus the VPC control
plane namespace on OPA port 8181. The public production Gateway was untouched.

The Helm `nova-keystone-test` Secret returned Keystone 401 and is not an active
test principal. A dedicated `dcn-p0-track-a-development` project and
`dcn-p0-track-a` user were therefore created with only `member` and `reader`.
That credential passed token issuance, catalog listing and unified quota lookup.
The temporary administrator Secret copy and discovery Pods were deleted. The
remaining development Secret is project-scoped and must not be promoted.

`core.openstack` now supplies fail-closed project-scoped REST adapters for Nova,
Neutron and Cinder with retry classification and reverse compensation.
`core.provider_probe` performs non-mutating checks against all six provider
APIs. No provider resource was created during this evidence collection.
Placement correctly returned 403 for project-level resource-provider inventory;
the acceptance probe therefore checks its version endpoint only and does not
grant the development principal a service-admin role.

The development manifest now uses a dedicated PostgreSQL StatefulSet/PVC and a
real RabbitMQ vhost `/dcn-p0-track-a-development`. Its unique user is restricted
to `dcn.track-a.*`; the durable topic exchange and audit queue receive the
transactional outbox. The runtime refuses SQLite whenever the mode is not
`development`. The real ASG scheduler deliberately reconciles desired=0 only;
desired>0 is surfaced as `DEGRADED` without creating fake instances.

Track A now targets the central `opa-pilot` decision endpoint directly. Its Pod
is labelled `dcn.ssu.ac.kr/central-opa-client=allowed`, and development egress
is restricted to Pods labelled `app=opa-pilot` in
`vpc-control-plane-system`, TCP 8181. The prior local OPA sidecar and copied
policy ConfigMap are removed. Deployment must wait until the separately owned
central OPA ingress policy admits that client label; the API remains fail-closed
until then.
