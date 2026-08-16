# Track C real-integration acceptance and safety boundary

## Current discovery evidence (2026-08-16 UTC)

The live Keystone catalog advertises `volumev3`, `image`, `sharev2`, `compute`,
`network`, `load-balancer`, `dns`, and `instance-ha`. The in-cluster RGW service
exists, but Keystone does not advertise an `object-store` endpoint. Track C
therefore reports RGW as unavailable instead of substituting an unscoped URL.
Masakari is catalogued, but the dedicated member credential receives HTTP 403
for failure segments. This intended least-privilege result keeps evacuation
execution blocked pending an explicitly reviewed operator role.

The development Track A and Track B services respond to `/healthz`. Their
canonical schemas are consumed by Track C, but the deployed Track A API has no
external operation-transition endpoint and Track B has no canonical event
ingestion endpoint. A health response is not treated as contract integration.

OPA is deployed at `opa-pilot.vpc-control-plane-system.svc:8181`. Decisions are
fail-closed: a missing response, missing `result`, or anything except an
explicit `allow: true` is denial.

No `dcn-resilience-development` Keystone project existed at discovery time.
An application credential must not be borrowed from a production service.

## Required credential input

Before integration mode is deployed, an operator must create a dedicated
Keystone project and a least-privilege application credential, then create the
development-only Secret `p1-resilience-openstack` with keys
`application-credential-id` and `application-credential-secret`. Values are
never committed or printed. The credential project is the only project that
read-only acceptance may enumerate.

## Acceptance sequence

1. Authenticate with the application credential and retain only the project ID
   and sanitized service availability result.
2. Resolve endpoints from the returned Keystone catalog; never hard-code a
   production ClusterIP.
3. Perform list operations with `limit=1` against the credential's project.
4. Check Track A/B health and separately require their canonical consumer
   endpoints. Missing endpoints keep readiness false.
5. Check OPA health and one explicit allow/deny decision using non-sensitive
   resource identifiers.
6. Confirm every `execute` and `compensate` call returns `destructive action
   fenced`. DR, restore, maintenance, probes, image promotion, and revocation
   remain dry-run only.

## Promotion and rollback

Integration mode may run only in `development-p1-resilience-operations` via
`./deploy.sh development p1-resilience-operations`. Production promotion is
blocked until the exact immutable digest passes the sequence above and Track
A/B publish their missing consumer endpoints. Rollback redeploys the previously
accepted digest and removes only the dedicated development application
credential; it never modifies tenant resources.
