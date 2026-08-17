"""Apply the platform's task-oriented Horizon information architecture."""

from collections import OrderedDict

import horizon
from horizon import base

# Preserve the VPC package's stock-instance action and URL customization.  The
# Horizon setting supports one customization module, so this platform module
# deliberately composes it before changing navigation metadata.
from openstack_vpc_dashboard import customization as _vpc_customization  # noqa: F401


def _rename_panel(dashboard, slug, name):
    try:
        dashboard.get_panel(slug).name = name
    except base.NotRegistered:
        pass


def _rename_group(dashboard, slug, name):
    try:
        dashboard.get_panel_group(slug).name = name
    except base.NotRegistered:
        pass


def _order_groups(dashboard, slugs):
    current = dashboard._panel_groups
    ordered = OrderedDict((slug, current[slug]) for slug in slugs if slug in current)
    ordered.update((slug, group) for slug, group in current.items() if slug not in ordered)
    dashboard._panel_groups = ordered


def _order_panels(dashboard, group_slug, slugs, keep_unlisted=True):
    try:
        group = dashboard.get_panel_group(group_slug)
    except base.NotRegistered:
        return
    present = list(group.panels)
    ordered = [slug for slug in slugs if slug in present]
    if keep_unlisted:
        ordered.extend(slug for slug in present if slug not in ordered)
    group.panels = ordered


def _hide_panels(dashboard, slugs):
    """Remove unsupported duplicate/advanced panels from this dashboard."""
    for slug in slugs:
        try:
            panel = dashboard.get_panel(slug)
        except base.NotRegistered:
            continue
        dashboard._unregister(panel.__class__)


project = horizon.get_dashboard("project")
_rename_group(project, "compute", "Compute")
_rename_group(project, "vpc", "Networking (VPC)")
_rename_group(project, "volumes", "Block Storage")
_rename_group(project, "share", "Shared File Storage")
_rename_group(project, "object_store", "Object Storage")
_rename_group(project, "container_infra", "Kubernetes")
_rename_group(project, "dns", "DNS")
_rename_group(project, "observability", "Monitoring & Alarms")
_rename_group(project, "default", "Developer Tools")

_rename_panel(project, "overview", "Compute Overview")
_rename_panel(project, "network_interfaces", "Network Interfaces")
_rename_panel(project, "volume_groups", "Volume Groups")
_rename_panel(project, "vg_snapshots", "Volume Group Snapshots")
_rename_panel(project, "containers", "Swift Containers")
_rename_panel(project, "cloud_s3", "S3 Access & Credentials")
_rename_panel(project, "shares", "File Shares")
_rename_panel(project, "share_snapshots", "File Share Snapshots")
_rename_panel(project, "share_networks", "File Share Networks")
_rename_panel(project, "cloud_metrics", "Metric Coverage")
_rename_panel(project, "cloud_alarms", "Alerts & Alarms")

_order_groups(
    project,
    (
        "compute",
        "vpc",
        "volumes",
        "share",
        "object_store",
        "container_infra",
        "dns",
        "observability",
        "default",
    ),
)
_order_panels(
    project,
    "compute",
    ("overview", "dcn_service_catalog", "instances", "network_interfaces", "images", "key_pairs", "server_groups"),
)
_order_panels(
    project,
    "vpc",
    (
        "vpc_topology",
        "network_operations",
        "vpcs",
        "vpc_subnets",
        "vpc_route_tables",
        "internet_gateways",
        "vpc_nat_gateways",
        "vpc_security_groups",
        "network_acls",
        "elastic_ips",
        "vpc_application_load_balancers",
        "vpc_network_load_balancers",
        "vpc_peerings",
        "transit_gateways",
        "private_dns_zones",
        "vpc_endpoints",
        "dhcp_option_sets",
        "flow_logs",
        "vpc_tags",
    ),
    keep_unlisted=False,
)
_order_panels(project, "share", ("shares", "share_snapshots", "share_networks"), keep_unlisted=False)
_order_panels(project, "object_store", ("cloud_s3", "containers"))
_order_panels(project, "observability", ("cloud_metrics", "cloud_alarms"))
_hide_panels(
    project,
    (
        "load_balancer",
        "security_services",
        "share_groups",
        "share_group_snapshots",
        "user_messages",
        "resource_locks",
    ),
)

identity = horizon.get_dashboard("identity")
identity.name = "Identity & Access"
_rename_panel(identity, "projects", "Projects & Members")
_rename_panel(identity, "users", "User Accounts")
_rename_panel(identity, "groups", "User Groups")
_rename_panel(identity, "roles", "Access Roles")
_rename_panel(identity, "credentials", "API Credentials")
_rename_panel(identity, "domains", "Identity Domains")
_order_panels(
    identity,
    "default",
    (
        "projects",
        "users",
        "groups",
        "roles",
        "application_credentials",
        "credentials",
        "domains",
    ),
)

admin = horizon.get_dashboard("admin")
_rename_panel(admin, "cloud_telemetry_health", "Telemetry Service Health")
_rename_group(admin, "share", "Shared File Storage")
