# P1 resilience operations development slice

This service is the independently testable Track C control-plane slice. It is
not wired to production OpenStack and cannot mutate production resources.

## Implemented safety contracts

| Workflow | Development endpoint | Enforced invariant |
| --- | --- | --- |
| backup and restore drill | `POST /v1/runs/backup-run` | application consistency cannot downgrade; freeze is compensated by thaw; isolated restore is cleaned |
| DR execution | `POST /v1/runs/dr-execution` | writable recovery requires fencing; live failover requires approval |
| tenant network diagnostic | `POST /v1/runs/network-diagnostic` | source is project-owned; destinations and probe duration/count are bounded; evidence is redacted |
| maintenance campaign | `POST /v1/runs/maintenance` | PCI, NUMA, hugepage and local-disk guests are not live-migrated; scheduler state is compensated |
| official image promotion | `POST /v1/runs/image-promotion` | owner, image class, digest, SBOM, provenance, signature, scan and boot test gates all pass |

All calls require `X-Verified-Project-ID` and `Idempotency-Key`. The identity
header is accepted only as a development fixture. Do not expose this service
until a Keystone-authenticated proxy overwrites (not forwards) that header and
OPA authorization is integrated.

```text
request -> project/idempotency gate -> SQLite operation journal
        -> versioned fake Track A Operation client
        -> workflow/adapters -> evidence digest
        -> versioned fake Track B Event client
```

The SQLite journal makes completed steps resumable and prevents duplicate
external actions after restart. OpenStack adapters are intentionally absent:
the next integration slice must replace `DevelopmentAdapter` with scoped
Keystone service clients and preserve the workflow tests.

## Test

```bash
PYTHONPATH=services/resilience python3 -m unittest discover \
  -s services/resilience/tests -v
services/resilience/tests/run-failure-drills.sh
```

## Development deployment

Build `services/resilience/Dockerfile`, push it to the development registry,
and capture the repository digest. The component rejects tags:

```bash
export P1_RESILIENCE_IMAGE='registry.example/resilience@sha256:<64-hex-digest>'
./deploy.sh development p1-resilience-operations
```

The development manifest has no ingress and no service-account token. It runs
only on the development-labelled utility node and uses non-authoritative PVC
state. Verification is performed inside the pod until the authenticated
development API edge is supplied by the integration owner.
