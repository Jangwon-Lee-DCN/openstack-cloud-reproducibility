# Octavia with OVN and Amphora Providers

## Result

Octavia exposes both providers:

- `ovn` is the default provider for efficient native OVN L4 load balancing.
- `amphora` provides appliance-based load balancing and features not supplied
  by the OVN provider.

The API, driver-agent, housekeeping, worker, and health-manager control-plane
roles each run on both controllers. The worker and health-manager are
DaemonSets because their Neutron management ports and addresses are
node-specific. MariaDB and RabbitMQ retain durable control-plane state.

## External interfaces

| Interface | Address |
| --- | --- |
| Public Octavia API | `https://cloud.dcn.ssu.ac.kr/load-balancer` |
| Internal OpenStack API Gateway | `https://api.internal.cloud.dcn.ssu.ac.kr` |
| Skyline | `https://cloud.dcn.ssu.ac.kr/` |
| Horizon fallback | `https://cloud.dcn.ssu.ac.kr/horizon/` |

Skyline maps the `load-balancer` service to Octavia. Horizon uses the
`octavia-dashboard` 2026.1 plugin in the digest-pinned custom Horizon image.

## Amphora resources

The idempotent
`scripts/reconcile-octavia-amphora-resources.sh` creates or reconciles:

| Resource | PoC value |
| --- | --- |
| Management network | `lb-mgmt-net` |
| Management subnet | `172.31.255.0/24` |
| Amphora flavor | `m1.amphora` (1 vCPU, 1 GiB RAM, 3 GiB disk) |
| Security group | `lb-mgmt-sec-grp` |
| Keypair | `octavia-key` |
| Glance image tag | `amphora` |
| Topology | `ACTIVE_STANDBY` |

The committed image name
`amphora-x64-haproxy-ubuntu-jammy-poc` identifies an upstream **test-only**
image. It is acceptable only for this PoC. Production must build and validate
an Amphora image with Octavia diskimage-builder that matches the deployed
OpenStack release and the site's security baseline.

The Amphora server and client CA materials are stored only as a SOPS-encrypted
Kubernetes Secret in
`secrets/octavia-amphora-certs.secret.sops.yaml`. Never commit the decrypted
private keys. The reconciliation wrapper decrypts them directly into
`kubectl apply`.

## Internal CA trust

Octavia initially failed while resolving the image tagged `amphora` from the
internal Glance endpoint. Waiting for Pods did not help: this was a persistent
CA trust configuration omission.

Octavia's Glance client uses the shared Keystone authentication session when
the endpoint is discovered from the service catalog. A CA configured only in
the `[glance]` section is therefore insufficient unless a Glance endpoint is
explicitly overridden. The deployment now:

1. copies only `ca.crt` from the internal Gateway CA Secret into the
   `openstack` namespace;
2. mounts it at `/etc/ssl/certs/openstack-internal-ca.crt`;
3. sets `[service_auth] cafile` to that path; and
4. also sets the service-specific CA paths for Glance, Nova, and Cinder.

Both OpenSSL verification and Octavia worker's in-process
`ImageManager.get_image_id_by_tag()` lookup must pass before an Amphora test.

## Other site-specific fixes

- The chart initializes each management interface with the fixed address of
  its pre-created Neutron port. It skips DHCP after static initialization,
  avoiding raw-socket failures inside the container.
- Octavia uses an explicit RabbitMQ transport URL through the headless
  service. The Octavia RabbitMQ credential is URL-safe and is stored only in
  the SOPS-encrypted values file.
- The worker and health-manager images are digest pinned.
- The worker image extends the Airship 2026.1 image with the constrained
  `redis` Python package required by the Taskflow Redis/Sentinel jobboard.
- Taskflow persistence uses MariaDB and its jobboard uses the dedicated
  `octavia-valkey` release. The release has three Ceph-backed Valkey nodes,
  each with a Sentinel sidecar.
- Valkey data endpoints require authentication. Sentinel discovery is not
  authenticated because Octavia 2026.1/Taskflow intentionally does not pass
  the data-store credential to Sentinel. Sentinel is exposed only through a
  cluster-internal Service.

## Jobboard HA boundary

The Jobboard allows another worker to claim an unfinished flow after the
original worker dies and its claim expires. RabbitMQ alone does not provide
this behavior after a worker has acknowledged a request and started a
Taskflow.

The current three Sentinel voters are spread across only two Kubernetes nodes.
This is useful for worker and Pod failure testing, but it cannot retain a
majority after the loss of either arbitrary physical node. Production requires
at least three independent failure domains with one voting member in each.
The frozen deployment and its validation are under
`deployment/prerequisites/storage/octavia-jobboard/`.

Run the destructive in-flight recovery test only in a test project:

```bash
OCTAVIA_JOBBOARD_FAILOVER_TEST=YES \
  scripts/verify-octavia-jobboard-failover.sh
```

The script refuses to accept the result if another process changes the
Octavia Helm revision during the test.

The accepted live recovery test deleted the controller-1 worker while load
balancer `8f192126-5fa2-44c6-a009-b7fb58f02ff7` was `PENDING_CREATE`.
The controller-0 worker resumed the same flow after the claim expiry, and the
load balancer reached `ACTIVE` / `ONLINE`. Exactly two Amphorae remained: one
`MASTER` and one `BACKUP`, both `ALLOCATED`. The Jobboard remained enabled on
both replacement workers and Sentinel reported all three voters usable.

## Accepted Amphora E2E test

`scripts/verify-octavia-amphora-e2e.sh` reconciles and verifies an active/
standby Amphora load balancer with an HTTP listener, round-robin pool, two
members, and a Floating IP.

The accepted live test produced:

| Resource | Result |
| --- | --- |
| Load balancer | `amphora-e2e-lb`, `ACTIVE` / `ONLINE` |
| Provider | `amphora` |
| VIP | `10.42.0.77` |
| Floating IP | `192.168.21.144` |
| Amphorae | one `MASTER`, one `BACKUP`, both `ALLOCATED` |
| Traffic | 8 requests: 4 to `backend-1`, 4 to `backend-2` |

Both Amphora VMs currently land on `controller-0`, the only compute node in
this PoC. Active/standby protects against an Amphora guest failure, but it
does not provide compute-host fault tolerance until another compute node and
appropriate scheduling policy are added.

## OVN operation recovery

The OVN provider has no Taskflow jobboard for API-to-provider operations. If a
driver-agent rollout loses the final status callback after OVN has accepted a
change, Octavia can remain in `PENDING_*`. Use
`deploy/scripts/recover-octavia-ovn-pending.sh` to audit operations older than
15 minutes. Explicit recovery runs the provider's single-ID sync and reports
the reconstructed hierarchy through the normal status socket; it never writes
Octavia database rows directly and blocks while Helm or driver-agent is
rolling out.

## Provider guidance

The raw Octavia API still exposes an explicit provider, but the VPC control
plane computes it from intent: native TCP/UDP/SCTP with `SOURCE_IP_PORT`
selects OVN, while HTTP-family listeners or
`ROUND_ROBIN`/`LEAST_CONNECTIONS` select Amphora. The CR does not expose a
free-form provider knob. Selection is recorded in status, and a spec edit that
would require changing an existing Octavia LB's immutable provider is refused
instead of silently recreating the LB and changing its VIP.

TCP has live coverage across local, VpcPeering, and real TransitGateway
members; Amphora HTTP has live traffic coverage. Cross-VPC UDP/SCTP and the
Amphora TLS variants remain explicit test gaps. IPv6 is not a platform claim
until the VPC and transit models become dual-stack.

## State observability

`deploy/monitoring/scripts/audit-octavia-state.sh` compares the live Octavia
API and OVN NB database for long `PENDING_*` operations, orphaned
cross-router ownership, dangling UUID-named OVN LB rows, and empty nexthops.
It is read-only and can publish bounded metrics to Pushgateway. The
Octavia audit section in the consolidated `OpenStack Platform Operations`
Grafana dashboard and the `octavia.state-audit` PrometheusRule group are
deployed from `deploy/monitoring/manifests`; response guidance is in
`deploy/monitoring/docs/octavia-state-audit.md`.
