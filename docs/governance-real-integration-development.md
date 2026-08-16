# Governance real-integration development acceptance

This slice removes the fake-provider runtime path. It is deployable only in
`development-p1-governance-services`; production mode exits before listening.

## Connected topology

```text
Keystone token -> Governance API -> Keystone self-token validation
                              \-> OPA vpc.authz decision (read/project-write)

Governance worker -> development PostgreSQL (checkpoint schema)
                  -> RabbitMQ /ceilometer vhost (dedicated durable queue)
                  -> Gnocchi / Barbican / Designate / Octavia adapters
```

The API exposes `/readyz`. Required providers are closed over an explicit list;
an absent or unreachable required endpoint returns HTTP 503. Optional providers
are listed as blockers and never replaced by deterministic fakes.

## Platform discovery and blockers

| Integration | Development state |
| --- | --- |
| Keystone | discovered at `keystone-api.openstack.svc:5000`; self-token validation implemented |
| OPA | discovered at `opa-pilot.vpc-control-plane-system.svc:8181`; `vpc.authz/decision` contract used |
| PostgreSQL | dedicated ephemeral development instance, immutable image digest |
| RabbitMQ | real platform broker; least-privilege Ceilometer vhost credential copied without decoding into the development namespace |
| Gnocchi | real API adapter and authenticated probe implemented |
| Barbican / Designate / Octavia | real API adapters and authenticated probes implemented |
| Nova / Cinder / Neutron / Glance native tags | endpoint adapter slots present; service-specific mutation acceptance still blocked on a governance application credential |
| CloudKitty | **blocked: no service/endpoints discovered** |
| SMTP | **blocked: no platform SMTP relay or approved test-sink endpoint discovered** |
| Webhook | **blocked: `hooks.dev.dcn.ssu.ac.kr` test sink is not deployed** |
| Audit search/index/export backend | **blocked: no dedicated append-only/index backend discovered** |

OpenStack mutation adapters require a least-privilege application credential and
the resource prefix `governance-dev-`. An admin password is not embedded or
copied. Until that credential is provisioned, the worker reports
`blocked_missing_application_credential` and does not mutate OpenStack.

## Acceptance

1. Run the full repository verifier and Helm client dry-run.
2. Build API and worker images once and record their registry digests.
3. Deploy only with `./deploy.sh development p1-governance-services`.
4. Verify both workloads remain on `dcn-1b-utility-0`, `/healthz` is healthy,
   `/readyz` reports every required provider configured, and PostgreSQL contains
   `governance_worker_checkpoint`.
5. Verify the Rabbit queue exists without consuming or altering service queues.
6. Use only `governance-dev-*` resources for later authenticated provider tests.

## Rollback

Redeploy the previously accepted API/worker digests with the same development
component. The development PostgreSQL volume is non-authoritative `emptyDir`;
rollback does not touch OpenStack service databases, Rabbit service queues, or
production resources. Remove only the dedicated `governance.events` queue if a
full development teardown is requested.
