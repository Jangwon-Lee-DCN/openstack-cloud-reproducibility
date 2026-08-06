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
# Local changes (see docs/proposals/iam-hardening/README.md, "New permission
# tier: self-service project lifecycle"): IndexView.get_data() gains a
# fallback when the admin-style project listing call fails, right where
# the original raised a generic error. Later (see "Splitting Identity >
# Projects into real vs. platform/service projects"), IndexView is
# rebuilt on horizon.tables.MultiTableView -- the single get_data() call
# becomes _fetch_and_split_tenants() (same fetch logic, unchanged) plus
# classify_tenant() and two get_<table>_data() methods. Everything else
# is an unmodified copy of the upstream file, kept whole (rather than
# monkeypatching methods from outside it) so a diff against the real
# upstream file shows exactly these additions.

from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from horizon import exceptions
from horizon import messages
from horizon import tables
from horizon import tabs
from horizon.utils import memoized
from horizon import workflows

from openstack_dashboard import api
from openstack_dashboard.api import keystone
from openstack_dashboard import policy
from openstack_dashboard import usage
from openstack_dashboard.usage import quotas

from openstack_dashboard.dashboards.identity.projects \
    import tables as project_tables
from openstack_dashboard.dashboards.identity.projects \
    import tabs as project_tabs
from openstack_dashboard.dashboards.identity.projects \
    import workflows as project_workflows
from openstack_dashboard.dashboards.project.overview \
    import views as project_views
from openstack_dashboard.utils import identity
from openstack_dashboard.utils import settings as setting_utils

PROJECT_INFO_FIELDS = ("domain_id",
                       "domain_name",
                       "name",
                       "description",
                       "enabled")

INDEX_URL = "horizon:identity:projects:index"


class TenantContextMixin(object):
    @memoized.memoized_method
    def get_object(self):
        tenant_id = self.kwargs['tenant_id']
        try:
            return api.keystone.tenant_get(self.request, tenant_id, admin=True)
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve project information.'),
                              redirect=reverse(INDEX_URL))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tenant'] = self.get_object()
        return context


# Domain this whole self-service line of features targets (see "New
# permission tier: self-service project lifecycle") -- the only domain a
# real end user would ever create/manage a project in through this UI.
# Everything else (Default, service, magnum, heat, ...) exists for
# OpenStack's own bootstrapping and per-service accounts, never touched
# by a human through Identity > Projects in normal operation.
_SELF_SERVICE_DOMAIN_NAME = "dcn"
# Project name patterns openstack-helm/kolla-ansible bootstrapping is
# known to create in THIS deployment, kept as a second signal alongside
# the domain check above (belt-and-suspenders in case a service project
# somehow ever lands inside the dcn domain, which none currently do).
_SERVICE_PROJECT_NAMES = {"service", "admin"}
_SERVICE_PROJECT_NAME_PREFIXES = ("internal_",)
# Keystone's own bootstrap/service project descriptions -- observed live
# ("Bootstrap project for initializing the cloud.", "Service Project for
# <service>") -- checked as a prefix since the service name varies.
_SERVICE_DESCRIPTION_PREFIXES = ("Bootstrap project", "Service Project for")


class IndexView(tables.MultiTableView):
    # One inventory with an explicit Project Type column.  The earlier two
    # stacked tables duplicated controls and made the classification look like
    # two different resources even though both are Keystone projects.
    table_classes = (project_tables.TenantsTable,)
    template_name = 'identity/projects/index.html'
    page_title = _("Projects")

    @staticmethod
    def classify_tenant(tenant, domain_name):
        """True if `tenant` looks like an OpenStack-service/platform-
        created project rather than a real one a human should be
        editing through this self-service UI -- see the module-level
        comment above each signal for where it comes from. Domain is
        checked first and normally decides it alone (every project seen
        live outside the dcn domain is a service project of some kind,
        every real self-service project is created inside it); the
        name/description checks are a safety net, not the primary
        signal."""
        if domain_name and domain_name.lower() != _SELF_SERVICE_DOMAIN_NAME:
            return True
        name = getattr(tenant, "name", "") or ""
        if name in _SERVICE_PROJECT_NAMES or name.startswith(_SERVICE_PROJECT_NAME_PREFIXES):
            return True
        description = getattr(tenant, "description", "") or ""
        return description.startswith(_SERVICE_DESCRIPTION_PREFIXES)

    def needs_filter_first(self, table):
        return self._needs_filter_first

    def has_more_data(self, table):
        return self._more.get(table._meta.name, False)

    def get_filters(self, filters=None, filters_map=None):
        # tables.DataTableView.get_filters() (the version this is adapted
        # from) reads off self.table, a single memoized table instance
        # that only exists on that single-table base class.
        # MultiTableView has no such attribute -- there are two tables,
        # so this sources filters from TenantsTable specifically (the
        # "real projects" table), which is also the only one of the two
        # still carrying a TenantFilterAction -- see ServiceProjectsTable
        # for why the other one deliberately doesn't.
        filters = filters or {}
        filters_map = filters_map or {}
        table = self.get_tables().get(project_tables.TenantsTable._meta.name)
        filter_action = table._meta._filter_action if table else None
        if filter_action:
            filter_field = table.get_filter_field()
            if filter_action.is_api_filter(filter_field):
                filter_string = table.get_filter_string().strip()
                if filter_field and filter_string:
                    filter_map = filters_map.get(filter_field, {})
                    filters[filter_field] = filter_string
                    for k, v in filter_map.items():
                        if filter_string.lower() == k:
                            filters[filter_field] = v
                            break
        return filters

    def _fetch_and_split_tenants(self):
        # Same fetch as the original single-table get_data() (unchanged
        # below), just followed by a classify_tenant() split instead of
        # returning one flat list. Cached on the instance since
        # MultiTableView calls get_tenants_data() and
        # get_service_tenants_data() separately but both need the exact
        # same underlying fetch -- fetching twice would double the
        # Keystone calls and risk the two tables disagreeing if
        # something changed between them.
        if hasattr(self, "_split_tenants"):
            return self._split_tenants

        tenants = []
        # Both tables' pagination markers are read here since whichever
        # table's "next page" link was clicked is the one whose marker
        # will be present; the other stays None (first page).
        marker = (
            self.request.GET.get(project_tables.TenantsTable._meta.pagination_param)
            or self.request.GET.get(project_tables.ServiceProjectsTable._meta.pagination_param)
        )
        self._more = {}
        filters = self.get_filters()

        self._needs_filter_first = False

        if policy.check((("identity", "identity:list_projects"),),
                        self.request):

            # If filter_first is set and if there are not other filters
            # selected, then search criteria must be provided and
            # return an empty list
            if (setting_utils.get_dict_config(
                    'FILTER_DATA_FIRST', 'identity.projects') and not filters):
                self._needs_filter_first = True
                self._split_tenants = ([], [])
                return self._split_tenants

            domain_id = identity.get_domain_id_for_operation(self.request)
            more = False
            try:
                tenants, more = api.keystone.tenant_list(
                    self.request,
                    domain=domain_id,
                    paginate=True,
                    filters=filters,
                    marker=marker)
            except Exception:
                # Horizon's own local policy.check() for
                # identity:list_projects can pass even when Keystone's
                # real (authoritative) policy rejects the actual call --
                # confirmed live, the hard way: this deployment's
                # is_domain_admin() check
                # (identity:admin_and_matching_domain_id) fails open for
                # *every* user, because that policy rule is not defined
                # anywhere in default_policies/keystone.yaml (the same
                # quirk documented for the Create/Delete self-service
                # actions below). Every ordinary project-scoped user
                # (in particular: anyone using the new "Create Project
                # (Self-Service)" action, who is admin of exactly one
                # project and nothing domain-wide) was hitting a scary
                # "Unable to retrieve project list" error here every
                # single time, confirmed against the live Keystone log:
                # `keystone.exception.ForbiddenAction: You are not
                # authorized to perform the requested action:
                # identity:list_projects.` Fall back to the same
                # self-service listing the elif branch below already
                # uses for users who never had list_projects in the
                # first place, instead of surfacing that as an error.
                try:
                    tenants, more = api.keystone.tenant_list(
                        self.request,
                        user=self.request.user.id,
                        paginate=True,
                        marker=marker,
                        filters=filters,
                        admin=False)
                except Exception:
                    exceptions.handle(self.request,
                                      _("Unable to retrieve project list."))
        elif policy.check((("identity", "identity:list_user_projects"),),
                          self.request):
            more = False
            try:
                tenants, more = api.keystone.tenant_list(
                    self.request,
                    user=self.request.user.id,
                    paginate=True,
                    marker=marker,
                    filters=filters,
                    admin=False)
            except Exception:
                exceptions.handle(self.request,
                                  _("Unable to retrieve project information."))
        else:
            more = False
            msg = \
                _("Insufficient privilege level to view project information.")
            messages.info(self.request, msg)

        domain_lookup = api.keystone.domain_lookup(self.request)
        for t in tenants:
            t.domain_name = domain_lookup.get(t.domain_id)

        real, service = [], []
        for t in tenants:
            is_service = self.classify_tenant(t, t.domain_name)
            t.project_type = _("Platform / Service") if is_service else _("User Project")
            (service if is_service else real).append(t)

        # Both tables report the same "more" flag from the single
        # underlying paginated fetch -- there's no way to know
        # separately whether more *real* vs. more *service* projects
        # remain without fetching every page up front, which would
        # defeat the point of pagination. Slightly imprecise (a "next"
        # link might appear on a table that turns out to have no more
        # matches once the next page is split), but never wrong in the
        # unsafe direction: it undershoots into "click next and see",
        # not into hiding real data.
        self._more = {
            project_tables.TenantsTable._meta.name: more,
            project_tables.ServiceProjectsTable._meta.name: more,
        }
        self._split_tenants = (real, service)
        return self._split_tenants

    def get_tenants_data(self):
        real, service = self._fetch_and_split_tenants()
        return real + service

    def get_service_tenants_data(self):
        _real, service = self._fetch_and_split_tenants()
        return service


class ProjectUsageView(usage.UsageView):
    table_class = usage.IdentityProjectUsagesTable
    usage_class = usage.ProjectUsage
    template_name = 'identity/projects/usage.html'
    csv_response_class = project_views.ProjectUsageCsvRenderer
    csv_template_name = 'project/overview/usage.csv'
    page_title = _("Project Usage")

    def get_data(self):
        super().get_data()
        return self.usage.get_instances()


class CreateProjectView(workflows.WorkflowView):
    workflow_class = project_workflows.CreateProject

    def get_initial(self):
        initial = super().get_initial()

        # Set the domain of the project
        domain = api.keystone.get_default_domain(self.request)
        initial["domain_id"] = domain.id
        initial["domain_name"] = domain.name

        return initial


class UpdateProjectView(workflows.WorkflowView):
    workflow_class = project_workflows.UpdateProject

    def get_initial(self):
        initial = super().get_initial()

        project_id = self.kwargs['tenant_id']
        initial['project_id'] = project_id

        try:
            # get initial project info
            project_info = api.keystone.tenant_get(self.request, project_id,
                                                   admin=True)
            for field in PROJECT_INFO_FIELDS:
                initial[field] = getattr(project_info, field, None)

            # get extra columns info
            ex_info = settings.PROJECT_TABLE_EXTRA_INFO
            for ex_field in ex_info:
                initial[ex_field] = getattr(project_info, ex_field, None)

            # Retrieve the domain name where the project belong
            try:
                if policy.check((("identity", "identity:get_domain"),),
                                self.request):
                    domain = api.keystone.domain_get(self.request,
                                                     initial["domain_id"])
                    initial["domain_name"] = domain.name

                else:
                    domain = api.keystone.get_default_domain(self.request)
                    initial["domain_name"] = domain.name

            except Exception:
                exceptions.handle(self.request,
                                  _('Unable to retrieve project domain.'),
                                  redirect=reverse(INDEX_URL))
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve project details.'),
                              redirect=reverse(INDEX_URL))
        return initial


class UpdateQuotasView(workflows.WorkflowView):
    workflow_class = project_workflows.UpdateQuota

    def get_initial(self):
        initial = super().get_initial()
        project_id = self.kwargs['tenant_id']
        initial['project_id'] = project_id
        try:
            # get initial project quota
            if keystone.is_cloud_admin(self.request):
                quota_data = quotas.get_tenant_quota_data(self.request,
                                                          tenant_id=project_id)
                for field in quotas.QUOTA_FIELDS:
                    initial[field] = quota_data.get(field).limit
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve project quotas.'),
                              redirect=reverse(INDEX_URL))
        initial['disabled_quotas'] = quotas.get_disabled_quotas(self.request)
        return initial


class DetailProjectView(tabs.TabView):
    tab_group_class = project_tabs.ProjectDetailTabs
    template_name = 'horizon/common/_detail.html'
    page_title = "{{ project.name }}"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.get_data()
        table = project_tables.TenantsTable(self.request)
        context["project"] = project
        context["url"] = reverse(INDEX_URL)
        context["actions"] = table.render_row_actions(project)

        return context

    @memoized.memoized_method
    def get_data(self):
        try:
            project_id = self.kwargs['project_id']
            project = api.keystone.tenant_get(self.request, project_id)
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve project details.'),
                              redirect=reverse(INDEX_URL))
        return project

    def get_tabs(self, request, *args, **kwargs):
        project = self.get_data()
        return self.tab_group_class(request, project=project, **kwargs)
