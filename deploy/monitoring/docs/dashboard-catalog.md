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
