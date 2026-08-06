# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2012 Nebula, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# Local additions (see docs/proposals/iam-hardening/README.md, "New
# permission tier: self-service project lifecycle"): `create_selfservice`
# and, added later, `manage_members_selfservice`/
# `manage_members_selfservice_add`/`manage_members_selfservice_bulk_add`/
# `manage_members_selfservice_change_role`/
# `manage_members_selfservice_transfer_ownership`/`leave_selfservice`/
# `audit_log_selfservice`/`audit_log_selfservice_export`/`my_access`/
# `domain_projects_overview`/`role_bundles`/`create_role_bundle`/
# `role_bundles_audit_log`/`simulate_access_selfservice`/
# `manage_project_tags`/`application_credentials`/
# `create_application_credential` -- appended to the stock URL list below
# unchanged. Kept as a full copy of the upstream file (rather than
# trying to monkeypatch urlpatterns from outside it) so a diff against
# the real upstream file shows exactly these additions.

from django.urls import re_path

from openstack_dashboard.dashboards.identity.projects import views
from project_selfservice_dashboard import views as selfservice_views

urlpatterns = [
    re_path(r'^$', views.IndexView.as_view(), name='index'),
    re_path(r'^create$', views.CreateProjectView.as_view(), name='create'),
    re_path(r'^create_selfservice$',
            selfservice_views.CreateProjectSelfServiceView.as_view(),
            name='create_selfservice'),
    re_path(r'^my_access$',
            selfservice_views.MyAccessView.as_view(),
            name='my_access'),
    re_path(r'^domain_projects_overview$',
            selfservice_views.DomainProjectsOverviewView.as_view(),
            name='domain_projects_overview'),
    re_path(r'^role_bundles$',
            selfservice_views.RoleBundlesView.as_view(),
            name='role_bundles'),
    re_path(r'^role_bundles/create$',
            selfservice_views.CreateRoleBundleView.as_view(),
            name='create_role_bundle'),
    re_path(r'^role_bundles/audit_log$',
            selfservice_views.RoleBundlesAuditLogView.as_view(),
            name='role_bundles_audit_log'),
    re_path(r'^application_credentials$',
            selfservice_views.ApplicationCredentialsView.as_view(),
            name='application_credentials'),
    re_path(r'^application_credentials/create$',
            selfservice_views.CreateApplicationCredentialView.as_view(),
            name='create_application_credential'),
    re_path(r'^(?P<tenant_id>[^/]+)/update/$',
            views.UpdateProjectView.as_view(), name='update'),
    re_path(r'^(?P<project_id>[^/]+)/usage/$',
            views.ProjectUsageView.as_view(), name='usage'),
    re_path(r'^(?P<project_id>[^/]+)/detail/$',
            views.DetailProjectView.as_view(), name='detail'),
    re_path(r'^(?P<tenant_id>[^/]+)/update_quotas/$',
            views.UpdateQuotasView.as_view(), name='update_quotas'),
    re_path(r'^(?P<project_id>[^/]+)/manage_members_selfservice/$',
            selfservice_views.ManageMembersSelfServiceView.as_view(),
            name='manage_members_selfservice'),
    re_path(r'^(?P<project_id>[^/]+)/manage_members_selfservice/add$',
            selfservice_views.AddMemberView.as_view(),
            name='manage_members_selfservice_add'),
    re_path(r'^(?P<project_id>[^/]+)/manage_members_selfservice/bulk_add$',
            selfservice_views.BulkAddMemberView.as_view(),
            name='manage_members_selfservice_bulk_add'),
    re_path(r'^(?P<project_id>[^/]+)/manage_members_selfservice/(?P<user_id>[^/]+)/change_role$',
            selfservice_views.ChangeMemberRoleView.as_view(),
            name='manage_members_selfservice_change_role'),
    re_path(r'^(?P<project_id>[^/]+)/manage_members_selfservice/(?P<user_id>[^/]+)/transfer_ownership$',
            selfservice_views.TransferOwnershipView.as_view(),
            name='manage_members_selfservice_transfer_ownership'),
    re_path(r'^(?P<project_id>[^/]+)/groups/add$',
            selfservice_views.ProjectGroupView.as_view(), name='add_project_group'),
    re_path(r'^(?P<project_id>[^/]+)/groups/(?P<group_id>[^/]+)/roles$',
            selfservice_views.ProjectGroupView.as_view(), name='change_project_group_roles'),
    re_path(r'^(?P<project_id>[^/]+)/leave_selfservice$',
            selfservice_views.LeaveProjectView.as_view(),
            name='leave_selfservice'),
    re_path(r'^(?P<project_id>[^/]+)/audit_log_selfservice$',
            selfservice_views.AuditLogView.as_view(),
            name='audit_log_selfservice'),
    re_path(r'^(?P<project_id>[^/]+)/audit_log_selfservice/export$',
            selfservice_views.export_audit_log_csv,
            name='audit_log_selfservice_export'),
    re_path(r'^(?P<project_id>[^/]+)/simulate_access_selfservice$',
            selfservice_views.SimulateAccessView.as_view(),
            name='simulate_access_selfservice'),
    re_path(r'^(?P<project_id>[^/]+)/manage_project_tags$',
            selfservice_views.ManageProjectTagsView.as_view(),
            name='manage_project_tags'),
]
