# P1 resilience operations development slice

This service is the independently testable Track C control-plane slice. Its
fail-closed `integration` and `production` modes authenticate with a dedicated
Keystone application credential, resolve service endpoints from the scoped
catalog, and allow bounded read-only discovery. Mutation and compensation stay
fenced. See `../../docs/track-c-real-integration-acceptance.md` for the live
platform blockers and acceptance boundary.

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
external actions after restart. Real OpenStack adapters are intentionally absent:
the next integration slice must replace `DevelopmentAdapter` with scoped
Keystone service clients and preserve the workflow tests.

The second development slice adds explicit `discover/execute/observe/compensate`
ports and deterministic fakes for Cinder, Glance, Manila, RGW, Nova, Neutron,
Octavia, Designate and Masakari. It also fixes the following pure policies as
source-tested contracts:

- exclusive expiring operation leases and durable step checkpoints;
- backup retention protection for legal holds, active restores, running work
  and the latest successful recovery point;
- checksum, probe and cleanup-aware restore evidence;
- measured DR RPO/RTO values with fencing remaining a workflow precondition;
- ordered route, SG, NACL, NAT and load-balancer explanations with redaction;
- planned migration versus evacuation constraints and Masakari collision locks;
- official-image attestation and revoked-digest deactivation.

`contracts/` contains consumer fixtures for Track A Operation and Track B
Event `v1alpha1`. They are compatibility fixtures, not authority to freeze the
providers' final API.

## Resource API and controller loops

`GET /openapi.json` describes project-scoped CRUD, optimistic generation
updates, marker pagination and explicit reconcile actions for:

```text
backup-policies       backup-runs          restore-drills
protection-groups     dr-plans             dr-executions
network-diagnostics  maintenance-campaigns
image-products        image-builds         image-revocations
```

The runnable scheduler reconciles due backup policies and pending DR plans,
diagnostics, campaigns, image builds and revocations. Development fake
providers retain deterministic observations and compensation evidence. A
controller restart reads resource status and operation checkpoints before
issuing another action.

`RESILIENCE_MODE=production` is deliberately unavailable in this build. Even
when endpoints are configured, startup fails until real authenticated clients
are installed. This prevents the development identity header and fake
providers from being exposed as a production service.

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
