# Track B governance development slice 0.1.0

## Status and boundary

This commit is an independently testable API/control-model slice for Track B.
It is **not a production deployment** and it does not claim that SMTP, webhook,
Gnocchi, CloudKitty, Barbican, Designate, CA/ACME, OpenStack audit collectors or
native tag adapters are connected. Those credential-bearing workers remain
fail-closed until their individual egress, secret and checkpoint contracts are
accepted in development.

The slice provides one tenant-isolated API model for:

- canonical notification inbox/subscription desired state and deduplication;
- Decimal usage rating, rate-card authorization and budget validation;
- certificate policy and Barbican-reference-only rotation policy;
- append-only, redacted audit events with a verifiable SHA-256 chain;
- canonical tag policy, reserved system tags and scope precedence; and
- versioned fake `track-a.operation.v1alpha1` references without creating a
  competing generic task database.

The SQLite repository is deliberately non-authoritative development storage.
Production promotion requires PostgreSQL migrations, backup/restore acceptance,
Keystone middleware (not trusted identity headers), OPA decisions, real Track A
operations and independently reviewed worker adapters.

## Logical flow

```text
Keystone-authenticated development gateway
             |
             | injected domain/project/user/roles
             v
     Governance API 0.1.0
       |     |      |       |       |       |
   Notify  Usage  Budget  Cert   Rotation  Tags
       \     |      |       |       |      /
        +----+------+ Audit hash chain ----+
                         |
             fake Track A Operation v1alpha1

External workers and OpenStack adapters: NOT CONNECTED in this slice
Production namespaces/Gateways/Secrets: NOT REFERENCED
```

## Local acceptance

```bash
PYTHONPATH=services/governance-api/src \
  python3 -m unittest discover -s services/governance-api/tests -v

helm lint helm/governance \
  --set-string image.digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

helm template governance helm/governance \
  --namespace development-p1-governance-services \
  --set-string image.digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa

bash -n automation/development/components/p1-governance-services.sh
git diff --check
```

Acceptance proves duplicate requests return one resource, Project A cannot
read Project B, unsafe webhook targets are rejected, monetary rounding is
deterministic, secret material is rejected/redacted, audit tampering is found,
and users cannot inject reserved tags.

## Development deployment

Build and push the exact feature commit with an immutable digest using the
Dockerfile in `images/governance-api`. Record the registry-returned digest, not
the local image ID. Then, from the site delivery repository whose wrapper owns
the development boundary:

```bash
export GOVERNANCE_IMAGE_DIGEST=sha256:<registry-digest>
export GOVERNANCE_WORKER_IMAGE_DIGEST=sha256:<registry-digest>
./deploy.sh development p1-governance-services
```

The component refuses a mutable tag, the wrong namespace/name, or an absent
digest. The common development wrapper limits it to
`development-p1-governance-services`, `dcn-1b-utility-0`, the development
PriorityClass and `p1-governance-services.dev.dcn.ssu.ac.kr`. No command in
this change targets a production namespace, Gateway, node or values file.

## Rollback

Development application uses Helm `--atomic`, so a failed rollout returns to
the prior accepted revision. A manual development rollback is:

```bash
helm -n development-p1-governance-services history governance
helm -n development-p1-governance-services rollback governance <accepted-revision> --wait
```

For source rollback, revert the feature commit through a PR. The SQLite schema
in 0.1.0 is additive and contains no downgrade migration; development data is
non-authoritative and may be exported then discarded. Production promotion is
blocked until a PostgreSQL forward/restore procedure is implemented and tested.

## Remaining Track B gates

1. Replace trusted identity headers with Keystone token validation and OPA.
2. Exercise the PostgreSQL contract against a disposable HA development
   database, including migration/restore and cursor pagination.
3. Connect the tested outbox contract to RabbitMQ plus credential-backed SMTP
   and webhook adapters; persist nonce expiry and prove DLQ recovery.
4. Replace the deterministic telemetry source with Gnocchi/Ceilometer adapters
   and reconcile their totals against the immutable raw/rated ledger.
5. Integrate Designate/CA/Barbican/Octavia certificate overlap probes.
6. Implement credential-type Barbican rotators using the tested fencing and
   compensation contract, then run consumer failure injection.
7. Replace the HMAC audit fixture with asymmetric signing, object export,
   index rebuild, retention and legal hold.
8. Replace fake native tag adapters with Nova/Cinder/Neutron/Glance/Octavia
   clients and run event/poll drift loops.
9. Replace the fake Operation adapter after Track A publishes the accepted
   real contract and run cross-track contract tests.
10. Integrate the independently packaged Track B Horizon panel into shared
    Horizon only through a later reviewed integration change.

## Slice 0.2.0 — durable workflow contracts

The second source-tested slice adds the failure and compensation contracts that
must exist before any real external adapter is enabled:

- resource writes and an outbox event commit in one transaction;
- expiring worker leases, exponential retry, stale-lease recovery and bounded
  dead-letter transition;
- development SMTP/webhook fixtures with destination allowlists, DNS-result
  public-address checks, HMAC, timestamp windows, nonces and replay rejection;
- raw telemetry checkpoints plus an immutable Decimal-rated ledger. Missing
  meters stay explicitly `incomplete` and can be rated later without replaying
  or rewriting earlier entries;
- certificate and rotation compensation plans that restore old consumers,
  retire/revoke candidates and remove DNS challenges after partial failure;
- signed audit ingestion and a signed export manifest with payload/hash-chain
  verification. HMAC is a deterministic development fixture only; production
  requires an asymmetric signer backed by an approved key service;
- native tag adapter protocol, revision fencing, dry-run and drift reconciliation
  fakes; and
- transactional PostgreSQL migrations with tenant RLS plus a parameterized
  repository/session contract and `FOR UPDATE SKIP LOCKED` worker claim.

All queue envelopes contain identifiers only. No worker performs network I/O,
loads an external credential or calls SMTP, Gnocchi, Barbican, Designate,
Octavia, OpenStack APIs or a production database.

### 0.2 acceptance and rollback

`deploy/tests/governance/run.sh` covers stale lease takeover, retry-to-DLQ,
idempotent raw/rated telemetry, late rate coverage, DNS rebinding, bad HMAC,
replay, SMTP header injection, partial rotation rollback, signed audit tamper,
tag revision conflicts, PostgreSQL parameterization and RLS DDL.

The two PostgreSQL migrations are forward-only contracts and have not been run
against any cluster. Before a development PostgreSQL deployment, add a disposable
database apply/restore test and capture its exact image/dump versions. Rollback
of an accepted persistent schema is restore/forward-fix; never run ad-hoc `DROP`
or `TRUNCATE`. The current development Helm release still runs only the
non-authoritative SQLite API from slice 0.1 and remains undeployed.

## Slice 0.3.0 — complete fake boundary

The final pre-integration slice adds CRUD with optimistic revisions,
idempotent update/delete, bounded cursor pagination and matching OpenAPI paths.
The API and worker are independently buildable images, and the development
chart requires immutable digests for both.

`FakeScheduler` persists outbox progress across process restarts. Deterministic
budget, certificate, rotation and tag loops cover convergence, threshold
deduplication, DNS cleanup, consumer promotion and native-tag drift. API and
worker both refuse production mode; the worker also requires explicit fake
provider mode.

The independent Horizon package contains a development-endpoint-only client
and Notifications, Usage & Cost, Budgets, Certificates, Secret Rotation,
Audit and Tag Policy sections. It is not added to shared Horizon navigation.

Remaining work is now real integration only: Keystone/OPA, PostgreSQL/RabbitMQ,
SMTP/webhook, Gnocchi/Ceilometer/CloudKitty, CA/ACME/Designate,
Barbican/Octavia, OpenStack native tag clients, asymmetric audit export/index,
the real Track A client and shared Horizon composition.

## Machine-readable cross-track contracts

Track B consumes the canonical Track A schema published from Track A commit
`7225b63` through the repository-local fixture
`deploy/tests/governance/track-a-operation-v1alpha1.json`. The fixture is a
semantic copy, not a runtime cross-worktree dependency. Its 22 required fields,
`additionalProperties: false`, UUID/date-time formats and uppercase state enum
are validated against the Track B fake consumer.

Track B publishes
`services/governance-api/contracts/track-b/track-b.event.v1alpha1.schema.json`.
The top-level event contract is closed with `additionalProperties: false`; its
explicitly versioned `payload` object is the only open extension point. Tests
validate a real transactional-outbox producer result and reject undeclared
top-level fields, lowercase Track A states and missing required fields.
