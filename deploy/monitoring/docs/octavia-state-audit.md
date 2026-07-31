# Octavia state audit

`deploy/monitoring/scripts/audit-octavia-state.sh` is a read-only comparison
between the Octavia API and the live OVN northbound database. It runs the
inspection inside a Ready `octavia-driver-agent` Pod so the query uses the
same TLS, service credentials, and OVN IDL configuration as the provider.

The audit reports:

- `PENDING_CREATE`, `PENDING_UPDATE`, or `PENDING_DELETE` load balancers older
  than `OCTAVIA_PENDING_MIN_AGE_SECONDS` (default: 900 seconds);
- `octavia:cross_router_lb` policies or
  `octavia:cross_router_lb_route` routes whose owner LB no longer exists;
- UUID-named OVN `Load_Balancer` rows with no matching OVN-provider Octavia LB;
- owned reroute policies with `nexthops=[]` and owned source-policy routes with
  an empty `nexthop`.

Run it manually without changing state:

```bash
deploy/monitoring/scripts/audit-octavia-state.sh octavia-state-audit.json
```

Publish its bounded, non-resource-labelled counters to Prometheus Pushgateway:

```bash
PUSHGATEWAY_URL=http://prometheus-pushgateway.monitoring.svc.cluster.local:9091 \
  deploy/monitoring/scripts/audit-octavia-state.sh octavia-state-audit.json
```

Schedule that command every 15 minutes from the cluster operations runner.
The script exits `1` when it finds drift, after publishing metrics. It exits
`2` or `3` for invalid configuration or absence of a Ready driver-agent.

## Response

1. Preserve the JSON report and confirm that no Octavia or driver-agent rollout
   is in progress.
2. For a long OVN `PENDING_*` operation, use the separately guarded
   `deploy/scripts/recover-octavia-ovn-pending.sh`. Never edit Octavia database
   provisioning status directly.
3. Treat empty nexthops as traffic-impacting. Compare the owner token
   `<load-balancer-id>:<member-id>` to Octavia status before changing OVN.
4. Treat orphan ownership and dangling LB rows as review findings, not automatic
   deletion instructions. Verify lifecycle state in Octavia, Neutron, and
   controller audit logs first.

The Octavia section of the consolidated `OpenStack Platform Operations`
Grafana dashboard reads `octavia_state_audit_issues` and
`octavia_state_audit_last_success_timestamp_seconds`. Prometheus alerts
distinguish long pending and dangling rows (warning) from orphaned cross-router
ownership and invalid nexthops (critical). `OctaviaStateAuditStale` fires when
collection is missing or older than 30 minutes.
