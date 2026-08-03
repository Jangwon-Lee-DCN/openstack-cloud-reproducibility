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
# `manage_members_selfservice_add`/`manage_members_selfservice_change_role`
# -- appended to the stock URL list below unchanged. Kept as a full copy of
# the upstream file (rather than trying to monkeypatch urlpatterns from
# outside it) so a diff against the real upstream file shows exactly these
# additions.

from django.urls import re_path

from openstack_dashboard.dashboards.identity.projects import views
from project_selfservice_dashboard import views as selfservice_views

urlpatterns = [
    re_path(r'^$', views.IndexView.as_view(), name='index'),
    re_path(r'^create$', views.CreateProjectView.as_view(), name='create'),
    re_path(r'^create_selfservice$',
            selfservice_views.CreateProjectSelfServiceView.as_view(),
            name='create_selfservice'),
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
    re_path(r'^(?P<project_id>[^/]+)/manage_members_selfservice/(?P<user_id>[^/]+)/change_role$',
            selfservice_views.ChangeMemberRoleView.as_view(),
            name='manage_members_selfservice_change_role'),
]
