# Octavia with the OVN Provider

## Result

Octavia is deployed with OVN as the default provider. The PoC deliberately
does not deploy Amphora workers, health managers, management networks, or
Amphora certificates. This matches the cloud's OVN networking backend and
avoids operating guest load-balancer appliances until an Amphora-only feature
is required.

The API, driver-agent, and housekeeping deployments each have two replicas
with required hostname anti-affinity. One replica runs on each controller.
MariaDB and RabbitMQ retain the durable control-plane state; the OVN Northbound
database retains the programmed load-balancer state.

## External interfaces

| Interface | Address |
| --- | --- |
| Public Octavia API | `https://cloud.dcn.ssu.ac.kr/load-balancer` |
| Skyline | `https://cloud.dcn.ssu.ac.kr/` |
| Horizon fallback | `https://cloud.dcn.ssu.ac.kr/horizon/` |

The public API route returns `401` without a Keystone token, which confirms
that the Gateway route reaches Octavia without exposing an unauthenticated API.

Skyline maps the `load-balancer` service to Octavia. Horizon uses the
`octavia-dashboard` 2026.1 plugin in the digest-pinned custom Horizon image.

## Site-specific runtime requirements

The OVN provider must receive all NB and SB clustered database endpoints, not
one Kubernetes ClusterIP. A connection pinned to a follower can block provider
initialization. `scripts/reconcile-octavia.sh` discovers the current
EndpointSlice addresses and rewrites the HA remote lists before each upgrade.

Octavia API processes communicate with driver-agent processes through Unix
sockets. The upstream chart's per-Pod `emptyDir` does not make those sockets
visible to the API. The patched chart uses `/var/lib/octavia/run` as a
node-local hostPath and mounts it at `/var/run/octavia` in the API and
driver-agent Pods. Required anti-affinity ensures exactly one pair per
controller. The host directory must be owned by UID/GID `42424`.

Octavia's Neutron client is configured with `valid_interfaces = internal`.
Without it, the client selects the self-signed public Gateway endpoint and
fails certificate verification.

## E2E validation

The persistent validation resources are:

| Resource | Value |
| --- | --- |
| Load balancer | `octavia-e2e-lb` |
| Provider | `ovn` |
| VIP | `10.42.0.152` |
| Floating IP | `192.168.21.145` |
| Listener | TCP port 80 |
| Pool algorithm | `SOURCE_IP_PORT` |
| Members | `octavia-backend-1`, `octavia-backend-2` |

The backend security group permits TCP/80 from the public test clients.
OVN preserves the original source address, so a rule limited only to the
tenant subnet blocks public LB clients. Production rules should use the
narrowest known client CIDRs rather than `0.0.0.0/0`.

The Cirros backends use config drives for user data because the current PoC
metadata path did not deliver user data. Run the idempotent API and traffic
check from an OpenStack client Pod:

```bash
kubectl -n openstack create configmap octavia-e2e-verify \
  --from-file=verify-octavia-e2e.py=scripts/verify-octavia-e2e.py \
  --dry-run=client -o yaml | kubectl apply -f -
```

The accepted test returned both `backend-1` and `backend-2` through
`http://192.168.21.145/`.

## Provider boundary

OVN is suitable for the current L4 VPC-style PoC. It does not implement every
Octavia capability, including several statistics, flavor, availability-zone,
and advanced L7 features. Add Amphora as an additional provider when those
capabilities become requirements; do not replace OVN for basic native L4
load balancing without a measured reason.
