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
2. Implement PostgreSQL repositories, migrations, cursor pagination and HA.
3. Add outbox/lease workers with delivery retry, HMAC nonce/replay storage and
   DLQ, then SMTP/webhook development fixtures.
4. Integrate Gnocchi/Ceilometer checkpoints and immutable rated ledger.
5. Integrate Designate/CA/Barbican/Octavia certificate overlap probes.
6. Implement credential-type rotators with fenced two-phase rollback.
7. Add signed audit ingestion/export/index rebuild and retention/legal hold.
8. Add Nova/Cinder/Neutron/Glance/Octavia native tag adapters and drift loops.
9. Replace the fake Operation adapter after Track A publishes the accepted
   real contract and run cross-track contract tests.
10. Add the Track B Horizon panel only in its independently owned image path;
    common Horizon navigation remains an integration change.
