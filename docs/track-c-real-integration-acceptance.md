# Track C real-integration acceptance and safety boundary

## Current discovery evidence (2026-08-16 UTC)

The live Keystone catalog now advertises all nine required service types,
including scoped `object-store` and GET-only `instance-ha` access. Track C still
resolves every URL from the application-credential token catalog and never
substitutes a guessed ClusterIP.

The development Track A and Track B services respond to `/healthz`. Their
canonical schemas are consumed by Track C. Track A publishes the revision- and
idempotency-guarded `/v1/operations/{id}/transition` endpoint; Track B publishes
the project-scoped canonical `/v1/events` ingest endpoint.

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
4. Create a fenced Track A operation, then pass its UUID to Track C. Verify the
   canonical VALIDATING/SCHEDULED/RUNNING/SUCCEEDED timeline and monotonic
   revision/progress.
5. Verify Track B accepts the emitted canonical event once and returns its
   stored event on an identical idempotent replay.
6. Restart Track C and prove delivered checkpoints suppress duplicate calls;
   force each target down independently and retain bounded retry and DLQ
   evidence without changing the completed local workflow result.
5. Check OPA health and one explicit allow/deny decision using non-sensitive
   resource identifiers.
6. Confirm every `execute` and `compensate` call returns `destructive action
   fenced`. DR, restore, maintenance, probes, image promotion, and revocation
   remain dry-run only.

## Promotion and rollback

Integration mode may run only in `development-p1-resilience-operations` via
`./deploy.sh development p1-resilience-operations`. Production promotion is
blocked until the exact immutable digest passes the sequence above. Rollback redeploys the previously
accepted digest and removes only the dedicated development application
credential; it never modifies tenant resources.
