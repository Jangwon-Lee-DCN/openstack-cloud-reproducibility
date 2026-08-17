# octavia operational contract

This is the authoritative issue, remediation, reconciliation, and verification contract for `octavia`.

## Known issues and scope

## Affected baseline

- OpenStack-Helm chart `2026.1.0`
- Octavia `18.0.1.dev3`
- OVN Octavia provider `10.0.0`
- Two-controller Kubernetes PoC

## Symptoms

1. The upstream Octavia image did not contain the complete OVN provider
   dependency set.
2. Provider initialization blocked when a single OVN DB ClusterIP selected a
   follower.
3. `/v2/lbaas/providers` returned an empty list after API startup.
4. LB creation failed with TLS verification against the self-signed public
   Neutron endpoint.
5. Initial Cirros backends did not receive metadata user data.
6. Public LB requests timed out while backend TCP/80 only allowed the tenant
   CIDR.

## Root causes

- The OVN provider is not complete in the selected base image.
- Clustered OVSDB clients need all NB/SB remotes for leader discovery.
- The chart isolates driver-agent Unix sockets in a Pod-local `emptyDir`;
  Octavia API therefore cannot reach `status.sock`.
- Octavia's Neutron client selects the public service catalog interface unless
  `neutron.valid_interfaces` is set.
- The PoC metadata data path did not deliver user data; config drive is an
  independent delivery mechanism.
- OVN preserves client source addresses, so tenant-only backend ingress does
  not admit public clients.

## Amphora extension symptoms and root causes

1. The Amphora worker could not resolve the image tagged `amphora` because TLS
   verification failed against the internal Glance endpoint.
2. Configuring a CA only under `[glance]` did not fix catalog-discovered
   endpoints. The Glance client used Octavia's shared Keystone session, which
   requires `[service_auth] cafile`.
3. The chart expected DHCP on the Amphora management interfaces, but the
   node-bound Neutron ports already had fixed addresses. The container could
   not open the required raw DHCP socket.
4. A chart-generated multi-host RabbitMQ URL was parsed incorrectly when the
   password contained URL delimiter characters.
5. Enabling Taskflow jobboard failed because the selected Airship Octavia image
   lacks the optional Python Redis client.
6. After publishing a custom image, worker Pods on the uncached controller
   failed with `unauthorized` because the upstream worker and health-manager
   DaemonSets did not render the configured image pull Secret.
7. Sentinel discovery failed authentication even though the Valkey credential
   was correctly configured. Octavia 2026.1/Taskflow intentionally does not
   pass data-store credentials to Sentinel connections.

These are persistent configuration or image defects. Waiting for all Octavia
Pods to become Ready does not resolve them.

## Remediation

1. Build the image in `images/octavia-ovn` with the 2026.1 OVN provider and its
   constrained dependencies, then deploy the recorded Harbor digest.
2. Discover every NB and SB EndpointSlice address and configure comma-separated
   OVSDB remotes.
3. Patch the driver-agent chart volume from `emptyDir` to the node-local
   `/var/lib/octavia/run` hostPath. Mount the same path in Octavia API at
   `/var/run/octavia`.
4. Create that directory on both controllers with owner `42424:42424` and mode
   `0750`.
5. Use required hostname anti-affinity and two replicas for API, driver-agent,
   and housekeeping.
6. Set `[neutron] valid_interfaces = internal`.
7. Install the 2026.1 Octavia Horizon plugin in the frozen custom Horizon
   image and map Skyline's `load-balancer` service to `octavia`.
8. Use config-drive test backends and permit the intended client CIDRs on
   backend TCP/80.
9. Enable both `ovn` and `amphora`, keeping OVN as the default provider, and
   deploy two workers plus two health managers as node-bound DaemonSets.
10. Create the Amphora management network, fixed node ports, security group,
    flavor, keypair, image tag, and dual intermediate CA hierarchy with the
    idempotent reconciliation script.
11. Copy only the internal Gateway `ca.crt` into the OpenStack namespace,
    mount it in Octavia, and configure `[service_auth] cafile` in addition to
    the Glance, Nova, and Cinder CA options.
12. Initialize management interfaces from the fixed Neutron port address and
    skip DHCP when that address is present.
13. Use an explicit headless-service RabbitMQ transport URL and a URL-safe,
    independently rotated Octavia credential. Keep all credentials and
    private keys only in SOPS-encrypted files.
14. Build the digest-pinned worker image in `images/octavia-ovn` with the
    2026.1-constrained Redis Python client.
15. Deploy the frozen `prerequisites/octavia-jobboard` Valkey chart with three
    Ceph-backed data nodes and Sentinel sidecars, then enable the Redis
    Taskflow jobboard and MariaDB persistence.
16. Keep Valkey data authentication enabled. Leave Sentinel discovery
    unauthenticated because Octavia 2026.1/Taskflow does not pass the data
    credential to Sentinel.
17. Patch both Octavia DaemonSets to render image pull Secrets. The upstream
    DaemonSet templates omitted the helper used by the Deployment templates,
    which caused private worker images to fail on nodes without a cached copy.

## Reconciliation

1. Ensure `/var/lib/octavia/run` exists on every controller with numeric
   owner/group `42424`, mode `0750`.
2. Discover the current `ovn-ovsdb-nb` and `ovn-ovsdb-sb` EndpointSlice
   addresses. Never copy stale Pod IPs from an earlier cluster.
3. Update `deploy/values/site/octavia.yaml` with all discovered remotes.
4. Install and verify `prerequisites/octavia-jobboard` before enabling
   `jobboard_enabled`. Confirm Sentinel reports a reachable quorum and all
   three Ceph-backed Pods are Ready.
5. Apply `deploy/secrets/octavia-amphora-certs.secret.sops.yaml` by streaming
   SOPS output directly to `kubectl`; never persist its private keys.
6. Copy only `ca.crt` from the internal Gateway CA Secret into the `openstack`
   namespace. The wrapper performs this without exporting any CA private key.
7. Run `deploy/scripts/reconcile-octavia-amphora-resources.sh` to reconcile the
   management network, node ports, security group, flavor, keypair, and image
   tag. Replace the test-only image with a site-built image for production.
8. Decrypt `deploy/secrets/octavia.values.sops.yaml` only to a mode-`0600`
   temporary file and destroy it after Helm exits.
9. Upgrade the frozen patched Octavia chart with `--no-hooks` for ordinary
   reconciliation. Run the initial chart hooks when databases, Keystone
   service records, or RabbitMQ users do not yet exist.
10. Wait for two API, two driver-agent, two housekeeping, two worker, and two
   health-manager instances, split across the controllers.
11. Confirm both controller hostPaths contain `status.sock`, `get.sock`, and
   `stats.sock`.
12. Run the checks in `VERIFY.md`.
13. Keep `[service_auth] valid_interfaces = internal` and mount the internal
    CA in `octavia-driver-agent`. The OVN sync utility uses this session to
    read a targeted Octavia object; without it the SDK selects the public
    endpoint or fails TLS verification.
14. After rollout, audit long-lived OVN provider operations with
    `deploy/scripts/recover-octavia-ovn-pending.sh`. Recovery must be scoped to
    one ID and must not run while the Deployment or Helm release is changing.
15. Run `deploy/monitoring/scripts/audit-octavia-state.sh` every 15 minutes from
    the operations runner with `PUSHGATEWAY_URL` set. The audit also checks
    cross-router ownership, dangling OVN LB rows, and empty nexthops; it is
    intentionally read-only.

## Verification

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

## Tenant isolation

The patched Octavia chart resolves `[service_auth]` from
`endpoints.identity.auth.octavia`, not the chart's admin credentials. This
causes Nova, Neutron, and Glance operations for Amphora appliances to run in
the Octavia service project.

Required cloud-side resources are also service-project scoped:

- private production Amphora image;
- Amphora management security group;
- RBAC access to the provider-owned management network.

The requesting tenant continues to own the load-balancer API object and VIP,
but not the implementation VM. This is an authorization boundary rather than
a Horizon/Skyline display filter.

Nova must retain its default project-reader policy for
`os_compute_api:servers:detail`. Only the `get_all_tenants` variant is reserved
for admin and monitoring roles.
