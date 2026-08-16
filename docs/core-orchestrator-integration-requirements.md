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
   development SQLite volume.
4. Put the API behind Keystone auth middleware and an OPA policy decision point,
   stripping externally supplied identity headers at the proxy boundary.
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
