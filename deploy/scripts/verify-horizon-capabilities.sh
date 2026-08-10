#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-openstack}
selector='application=horizon,component=server'

test "$(kubectl -n "$NAMESPACE" get deployment horizon -o jsonpath='{.status.readyReplicas}')" = 2
test "$(kubectl -n "$NAMESPACE" get pods -l "$selector" -o jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' | sort -u | wc -l)" -ge 2

for pod in $(kubectl -n "$NAMESPACE" get pods -l "$selector" -o name); do
  kubectl -n "$NAMESPACE" exec "$pod" -- sh -c '
    set -eu
    python3 -c "import manila_ui, manilaclient, masakaridashboard, cloud_telemetry_dashboard, cloud_s3_dashboard"
    root=/var/lib/openstack/lib/python3.12/site-packages/openstack_dashboard
    for file in _1330_project_backups_panel.py _9010_manila_project_add_shares_panel_to_share_panel_group.py _50_masakaridashboard.py _1610_project_metrics.py _1620_project_alarms.py _2610_admin_telemetry_health.py _1930_project_s3.py; do
      test -f "$root/local/enabled/$file" -o -f "$root/enabled/$file"
    done
    cd /var/lib/openstack/lib/python3.12/site-packages
    DJANGO_SETTINGS_MODULE=openstack_dashboard.settings python3 - <<"PY"
import pymysql
pymysql.install_as_MySQLdb()
import django
django.setup()
import openstack_dashboard.urls
from django.conf import settings
from django.template.loader import get_template
from django.urls import reverse
from horizon import Horizon

assert settings.OPENSTACK_CINDER_FEATURES["enable_backup"] is True
for app in ("cloud_telemetry_dashboard", "cloud_s3_dashboard"):
    assert app in settings.INSTALLED_APPS
for template in (
    "cloud_telemetry_dashboard/metrics.html",
    "cloud_telemetry_dashboard/alarms.html",
    "cloud_telemetry_dashboard/health.html",
    "cloud_s3_dashboard/index.html",
    "cloud_s3_dashboard/create_bucket.html",
    "cloud_s3_dashboard/credential_created.html",
):
    get_template(template)
for name in (
    "horizon:project:cloud_metrics:index",
    "horizon:project:cloud_alarms:index",
    "horizon:project:cloud_s3:index",
    "horizon:admin:cloud_telemetry_health:index",
    "horizon:admin:project_operations:index",
    "horizon:project:shares:index",
    "horizon:masakaridashboard:segments:index",
):
    assert reverse(name).startswith("/horizon/")
project = Horizon.get_dashboard("project")
assert list(project.get_panel_groups()) == [
    "compute", "vpc", "volumes", "share", "object_store",
    "container_infra", "dns", "observability", "default",
]
assert project.get_panel_group("share").panels == [
    "shares", "share_snapshots", "share_networks",
]
assert project.get_panel_group("observability").panels == [
    "cloud_metrics", "cloud_alarms",
]
assert str(project.get_panel_group("observability").name) == "Monitoring & Alarms"
assert str(project.get_panel("cloud_metrics").name) == "Metric Coverage"
assert str(project.get_panel("cloud_s3").name) == "S3 Access & Credentials"
identity = Horizon.get_dashboard("identity")
assert str(identity.name) == "Identity & Access"
assert str(identity.get_panel("projects").name) == "Projects & Members"
assert str(identity.get_panel("users").name) == "User Accounts"
from openstack_dashboard.dashboards.identity.projects import tabs as project_tabs
from openstack_dashboard.dashboards.identity.projects import views as project_views
assert [tab.slug for tab in project_tabs.ProjectDetailTabs.tabs] == [
    "overview", "members", "groups", "quota_usage", "credentials", "health", "audit",
]
assert len(project_views.IndexView.table_classes) == 1
assert project_views.IndexView.table_classes[0]._meta.name == "tenants"
assert ("instance-ha", "context_is_admin") in Horizon.get_dashboard("masakaridashboard").policy_rules
PY
  '
done

curl -ksSf --resolve cloud.dcn.ssu.ac.kr:443:10.67.10.6 https://cloud.dcn.ssu.ac.kr/horizon/auth/login/ >/dev/null
echo "Horizon capability dashboard discovery and HA rollout passed."
