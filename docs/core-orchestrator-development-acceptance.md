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

- PostgreSQL migration and HA/failover acceptance
- worker lease, heartbeat, bounded retry, compensation and dead-letter worker
- real Keystone token validation and OPA decision integration
- Nova/Neutron/Cinder/Placement quota and mutation adapters
- Aodh webhook signature, cooldown clock and LB drain adapter
- native Nova soft-delete capability validation against deployed microversions
- three API replicas, multiple workers, metrics/SLO and 24-hour failure canary
- Horizon overlay after API semantics are accepted

Until every blocker is closed, `deploy/values/features/core-orchestrator.yaml`
remains disabled and no production Phase may reference it.
