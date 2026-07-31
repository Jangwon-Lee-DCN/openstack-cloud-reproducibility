# VERIFY: Octavia

## Control plane

```bash
helm -n openstack status octavia
kubectl -n openstack get pods -l application=octavia -o wide
kubectl -n openstack get deploy \
  octavia-api octavia-driver-agent octavia-housekeeping
```

Expected: two ready replicas for each deployment, split across the two
controllers.

## API and dashboards

```bash
curl -ksS -o /dev/null -w '%{http_code}\n' \
  https://cloud.dcn.ssu.ac.kr/load-balancer/v2/lbaas/providers
kubectl -n openstack exec deploy/horizon -- \
  python3 -c 'import octavia_dashboard; print(octavia_dashboard.__file__)'
```

The unauthenticated API response must be `401`. An authenticated provider query
must contain both `ovn` and `amphora`. Skyline runtime configuration must map
both the service and extension named `load-balancer` to `octavia`.

## Data plane

Run `deploy/scripts/verify-octavia-e2e.py` from a client container populated
with the standard Keystone `OS_*` variables. Acceptance requires:

- load balancer, listener, pool, and members remain `ACTIVE`;
- the load balancer remains `ONLINE`;
- provider is `ovn`;
- repeated HTTP requests to the LB Floating IP return responses from both
  backend names.

## Amphora provider

Run:

```bash
deploy/scripts/verify-octavia-amphora-e2e.sh
```

Acceptance requires:

- the internal Gateway certificate verifies against the CA mounted in the
  worker;
- the worker's in-process image lookup resolves the Glance image tagged
  `amphora`;
- one Amphora is `MASTER`, one is `BACKUP`, and both are `ALLOCATED`;
- the Amphora load balancer is `ACTIVE` and `ONLINE`; and
- repeated HTTP requests through its Floating IP reach both backends.

The PoC upstream image is explicitly test-only. A successful PoC test does not
approve that image for production.

## Taskflow Jobboard recovery

1. Confirm every worker has `jobboard_enabled = true`, can import
   `redis.sentinel.Sentinel`, and has the digest-pinned custom image.
2. Confirm `SENTINEL ckquorum octavia-jobboard` reports three usable
   Sentinels.
3. Start a new Amphora operation and record the worker processing it.
4. Delete that worker Pod while the load balancer is `PENDING_CREATE`.
5. Wait longer than `jobboard_expiration_time` and prove the other worker
   resumes the persisted flow.
6. Acceptance requires the load balancer to reach `ACTIVE` and `ONLINE`
   without duplicate Amphorae or orphaned Neutron ports.

Do not accept a test if another Helm reconciliation disables the Jobboard
during the flow. Record the Octavia Helm revision before and after the test.

Accepted PoC result: load balancer
`8f192126-5fa2-44c6-a009-b7fb58f02ff7` resumed on the controller-0 worker
after the active controller-1 worker was deleted. It reached `ACTIVE` /
`ONLINE` with exactly one `MASTER` and one `BACKUP` Amphora, both `ALLOCATED`.

## OVN provider pending-state recovery

An OVN operation can finish in Northbound DB while its final status callback
is lost during an API/driver-agent rollout. Audit OVN load balancers that have
remained `PENDING_*` for more than 15 minutes:

```bash
deploy/scripts/recover-octavia-ovn-pending.sh
```

The audit is read-only and exits non-zero when operator review is required.
Inspect the named LB and its OVN rows first. Targeted recovery is explicit and
never changes Octavia's database directly:

```bash
deploy/scripts/recover-octavia-ovn-pending.sh <load-balancer-id>
OCTAVIA_OVN_PENDING_RECOVERY=YES \
  deploy/scripts/recover-octavia-ovn-pending.sh <load-balancer-id>
```

The script refuses a non-OVN target, a state other than `PENDING_*`, a target
younger than the threshold, an unstable driver-agent Deployment, or an active
Helm operation. It invokes the provider's ID-targeted sync, which reconciles
OVN and sends status through Octavia's driver status socket. Acceptance
requires `ACTIVE`; a direct database `UPDATE` is not an accepted recovery.

## Octavia/OVN state audit

Run the wider, read-only state comparison and optionally publish its bounded
Prometheus counters:

```bash
deploy/monitoring/scripts/audit-octavia-state.sh octavia-state-audit.json
```

This detects long `PENDING_*` operations, orphaned cross-router ownership,
dangling UUID-named OVN LB rows, and empty policy/route nexthops. See
`deploy/monitoring/docs/octavia-state-audit.md`; findings do not authorize
automatic OVN deletion.
