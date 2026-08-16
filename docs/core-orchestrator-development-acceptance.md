# Track A core orchestrator — development acceptance and rollback

## Delivered development slice

This slice fixes the versioned core contract before any OpenStack provider is
allowed to mutate resources. It provides a durable transactional model in the
process database for Operation/events/outbox, signed preflight approvals,
immutable Launch Template versions, pinned Auto Scaling Group versions,
deduplicated bounded scaling signals, deletion protection, and capability-aware
recycle entries. Identity is accepted only from validated `X-Project-Id` and
`X-User-Id` headers; production integration must place the API behind the
Keystone auth proxy and must strip caller-supplied identity headers.

The development deployment deliberately uses one replica and an `emptyDir`
SQLite database. It is non-authoritative and validates API/runtime packaging
only. It must not be promoted as HA or durable production state.

The second source-tested slice adds lease expiry recovery, stale-worker
fencing, retry timestamps and persisted checkpoints. Provider boundaries are
explicit Nova/Neutron/Cinder-style interfaces; deterministic fakes prove
idempotent resume and reverse-order compensation without touching OpenStack.
Production authentication defaults to a short-lived HMAC assertion from a
trusted Keystone/OPA proxy and refuses raw identity headers. Raw headers are
available only when `CORE_AUTH_MODE=development`. Aodh events require a
timestamped signature and have a durable inbound replay ledger.
The event signature input is
`<unix-timestamp>.<canonical-JSON-body>` where canonical JSON uses sorted keys
and compact separators. The timestamp and signature travel in
`X-DCN-Event-Timestamp` and `X-DCN-Event-Signature`.

`migrations/postgresql/001_core.sql` and the PostgreSQL claim/outbox statements
define UUID, JSONB, timestamptz, uniqueness, runnable-index and
`FOR UPDATE SKIP LOCKED` semantics. They are a repository contract, not proof
that a live PostgreSQL failover test has passed.

The final pre-integration slice makes the fake system executable end to end:
the API persists normalized requests, the worker claims and executes them,
retryable failures use exponential bounded backoff, exhaustion enters a durable
dead-letter queue after compensation, and the scheduler reconciles ASG
desired/actual membership while honoring cooldown and protected instances.
All list APIs use bounded marker pagination. Template/ASG capacity lifecycle,
protection, recycle restore and privileged purge, preflight inventory and the
ordered Operation timeline are exposed by the HTTP contract and documented in
`openapi.yaml`.

An independent `images/horizon-core-orchestration-dashboard/` package consumes
only that contract. It is deliberately not composed into the shared Horizon
image. The development Pod contains API, worker and scheduler containers using
the same immutable image and disposable SQLite volume.

## Local acceptance

```bash
deploy/scripts/verify-core-orchestrator.sh
git diff --check
```

The tests cover idempotent replay/conflict, project isolation, terminal-state
guards, transactionally committed outbox events, preflight token binding,
immutable template versions, ASG version pinning and capacity bounds, alarm
deduplication, plaintext secret rejection, protection, restore capability, HTTP
identity enforcement and the `202 + Location` operation contract.
They also cover lease takeover/fencing, delayed retry/checkpoint resume,
provider compensation and restart idempotency, signed Keystone/OPA assertions,
signed/replayed Aodh events, and PostgreSQL migration/locking invariants.
Fake-provider E2E additionally covers API-to-worker success, ordered timeline,
restart safety, retry scheduling, DLQ compensation, ASG scale-out/scale-in,
cooldown, pagination and the full protect/recycle/restore/purge lifecycle.
The ASG resource-set suite additionally injects a crash after port creation,
proves checkpoint resume without a second member, retries a transient provider
failure against the same reservation, blocks protected scale-in, and verifies
reverse compensation leaves no fake-provider resources.

## Isolated development acceptance

Build `images/platform-core-orchestrator/Dockerfile`, push a development-only
tag, resolve it to its registry digest, then run from the site delivery repo:

```bash
export CORE_ORCHESTRATOR_IMAGE='registry.dcn.ssu.ac.kr/development/platform-core-orchestrator@sha256:<digest>'
./deploy.sh development p0-core-orchestration
```

The component refuses tags, production namespaces and non-development names.
The common wrapper additionally verifies node, namespace, quota, policy,
Gateway and TLS boundaries.

## Development rollback

Because the development DB is explicitly disposable, rollback is:

```bash
kubectl -n development-p0-core-orchestration rollout undo deployment/p0-core-orchestration
kubectl -n development-p0-core-orchestration rollout status deployment/p0-core-orchestration --timeout=5m
```

If a schema-breaking experiment was deployed, delete only the development
Deployment and let the accepted digest recreate its ephemeral database. Do not
reuse this procedure for production. Production rollback must retain the
PostgreSQL schema/data and deploy the previously accepted digest by the same
approved Phase.

## Promotion blockers

All remaining blockers require real integration or an integration environment:

- run the committed schema through a real PostgreSQL repository adapter and
  test HA/failover, migrations, backup and restore;
- execute the implemented Keystone-token/OPA boundary against live allow and
  deny decisions from the development route;
- run `python -m core.provider_probe` in the immutable development image, then
  perform create/compensate acceptance only in `dcn-p0-track-a-development`;
- implement Placement and Octavia mutation adapters (their current integration
  is intentionally read-only) and run quota, rollback, drain and orphan checks;
- connect a real Aodh webhook, rotate its credential and verify clock skew;
- validate native Nova soft-delete against the deployed microversion;
- run three API replicas, multiple workers and schedulers with RabbitMQ/outbox
  delivery, metrics/SLO and a 24-hour fault-injection canary;
- compose and browser-test the independent Horizon package in the accepted
  shared Horizon image.

Until every blocker is closed, `deploy/values/features/core-orchestrator.yaml`
remains disabled and no production Phase may reference it.
