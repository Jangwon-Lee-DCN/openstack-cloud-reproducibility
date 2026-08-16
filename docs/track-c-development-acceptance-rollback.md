# Track C development acceptance and rollback

## Promotion state

This change is a development-only slice. It does not declare the Track C ToDo
complete and supplies no production Phase, values, Gateway, Secret or live
OpenStack credentials. Production promotion is blocked until real Track A/B
contracts, Keystone/OPA middleware, OpenStack adapters and the five complete
failure-drill suites pass in the isolated boundary.

## Acceptance gates

1. Run `git diff --check` and the repository automation verifier.
2. Run all unit, API boundary and failure-drill tests documented in the
   service README.
3. Build the pinned-base Dockerfile and record the produced immutable digest.
4. Confirm `P1_RESILIENCE_IMAGE` contains `@sha256:` and run only:

   ```bash
   ./deploy.sh development p1-resilience-operations
   ```

5. The component verifier must prove:
   - the namespace is exactly `development-p1-resilience-operations`;
   - scheduling selects only `dcn.ssu.ac.kr/workload-class=development`;
   - the deployed image is digest-pinned;
   - health reports fake Track A/B integration explicitly;
   - requests without verified project identity return HTTP 401;
   - there is no HTTPRoute, production Gateway reference or service-account token.
   - the non-authoritative journal uses the development-local `dcn-local-rwo`
     StorageClass and does not attach PowerStore or production Ceph storage.
6. Preserve the tested Git SHA, image digest and test output in the development
   PR. Do not rebuild that image for later promotion.

## Failure-drill evidence covered by this slice

- backup failure after freeze invokes thaw;
- restart resumes completed backup steps without duplicate capture;
- absent DR fencing prevents storage recovery;
- cross-project network diagnostics never start a probe;
- migration failure restores the pre-campaign scheduler state;
- invalid official-image ownership prevents promotion.
- competing workers cannot steal a live operation lease, but an expired lease
  can be recovered from the last durable checkpoint;
- retention cannot expire running, held, actively restored or latest-success
  generations;
- declared network reachability with a failed probe is recorded as mismatch;
- active Masakari recovery blocks a competing maintenance campaign;
- a revoked image digest requires Glance deactivation.

These tests use deterministic adapters. They are contract evidence, not proof
that Cinder, Nova, Neutron/OVN, Octavia, Designate or Glance integration works.

## Rollback

Development application rollback is recoverable and component-scoped:

```bash
kubectl -n development-p1-resilience-operations scale \
  deployment/p1-resilience-operations --replicas=0
```

To restore a previously accepted build, set `P1_RESILIENCE_IMAGE` to its exact
accepted digest and rerun the same component. The SQLite schema in this slice
is additive and version 1 has no destructive migration. Preserve the PVC while
operations/evidence are under review.

After the evidence retention window, an operator may delete the development
namespace through the shared development cleanup procedure. Do not directly
delete production resources. Source rollback is a revert PR.

## Integration blockers

All remaining gates require real external integration:

- replace Track A `v1alpha1` fake transitions with the accepted Operation/Task,
  lock, cancellation, dry-run and compensation client;
- replace Track B `v1alpha1` fake events with its authenticated producer and
  validate notification/audit delivery and dead-letter behavior;
- install Keystone middleware that overwrites identity headers and enforce the
  final OPA action matrix on every collection/action;
- replace all nine deterministic provider fakes with scoped Cinder, Glance,
  Manila, RGW, Nova, Neutron/OVN, Octavia, Designate and Masakari clients;
- run disposable-project integration drills against real service quotas,
  asynchronous states, API microversions and failure behavior;
- integrate the independent Horizon package through the common navigation and
  authenticated `/resilience-api/` edge;
- build/push the container, record its immutable digest and run the common
  `./deploy.sh development p1-resilience-operations` wrapper;
- obtain explicit operator approval before any real failover, image promotion,
  production Phase or production data mutation.
