# OpenStack Grafana dashboard catalog

The custom dashboards are operator workflows, not metric inventories. Start at
`OpenStack Platform Operations`, then follow the affected service dashboard.
Kube-prometheus-stack and Loki upstream dashboards remain separately managed.

| Dashboard | Use it for |
|---|---|
| OpenStack Platform Operations | Incident triage across public APIs, workloads, MariaDB/RabbitMQ, capacity and firing alerts |
| OpenStack / Neutron Network Operations | Network API, inactive routers/ports/FIPs, OVN readiness, inventory, VPC drift and conflicts |
| OpenStack / Nova Compute Operations | Nova API/control plane, VM inventory, compute agents and Placement capacity |
| OpenStack / Octavia Load Balancer Operations | Octavia components, LB inventory, OVN state audit and provisioning alerts |
| OpenStack / Cinder Storage Operations | Cinder API/components, volume status, inventory and service CPU/memory |
| OpenStack / Keystone Identity Operations | Identity API, project credential bindings/lifecycle and identity alerts |
| OpenStack / MariaDB & RabbitMQ Operations | Galera latency/locks and RabbitMQ alarms, backlog, redelivery and saturation |

Every PromQL expression is validated against the live Prometheus API before
deployment. A panel is omitted when the installed exporter exposes a metric
name but publishes no series: notably per-VM status, per-Amphora status and
Keystone project/user totals at the time of this catalog. Dashboard descriptions
record these gaps rather than rendering misleading empty panels or zero values.

Dashboard ConfigMaps are loaded through the Grafana sidecar and have stable
UIDs. The consolidated manifest is
`deploy/monitoring/manifests/openstack-service-dashboards.yaml`; the platform
landing page is `deploy/monitoring/manifests/dashboard.yaml`.
## Identity & access denials (HTTP 403), on OpenStack Platform Operations

Added to the platform landing page rather than as a separate dashboard, to
match the existing convention that cross-service alert/incident state
lives there. Backs the `OpenStackAPIAccessDenied` Loki ruler alert (see
`deploy/scripts/../../prerequisites/observability/logging` in
`openstack-cloud-services` for the alert rule itself, and
`docs/proposals/iam-hardening/README.md`'s "Baseline hardening" section
in `openstack-cloud-services` for the full writeup) with the dashboard the
alert's own description was missing: 1h/24h denial counts, distinct
source-IP and denied-path counts, a 5-minute-bucket time series matching
the alert's own query, and three breakdown panels (top denied paths, top
source IPs, denials by pod) plus a raw log panel for drilling into the
exact request behind any spike.

All panels use the Loki datasource with `{namespace="openstack"} |= " 403 "`
as the base selector -- deliberately a generic access-log status-code
match (Apache/WSGI combined log format), not a per-service exception
message, so it covers every OpenStack service uniformly. The per-path and
per-IP breakdown panels additionally parse the combined log format with a
LogQL `regexp` stage (`client_ip`, `method`, `path`, `status` capture
groups) to enable the `sum by (path)` / `sum by (client_ip)` aggregations
-- every query in this section was run directly against live Loki and
confirmed to return real data before being committed, not just checked
for JSON/LogQL syntax validity.

## VPC Control Plane / Network Interfaces

This dashboard is the operational view for managed ENIs. Its chained project
namespace, VPC, Subnet, and Network Interface variables come from
`vpc_network_interface_info`. It includes a 24-hour attachment success SLO,
current report-only drift, automatic repair activity, failure-reason links to
Loki, and request-ID/trace correlation links to Tempo.

The Tempo link uses TraceQL attribute `span."request.id"`; the VPC facade's HTTP
instrumentation attaches its `X-Request-ID` to that span attribute and exports
through the cluster Tempo distributor. Run
`deploy/monitoring/scripts/test-dashboard-json.py` to reject
invalid embedded JSON, duplicate dashboard/panel IDs, or removal of the
Prometheus/Loki/Tempo correlation contract before applying ConfigMaps.
