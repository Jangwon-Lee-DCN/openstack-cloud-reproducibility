# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# Local additions (see docs/proposals/iam-hardening/README.md, "New
# permission tier: self-service project lifecycle"): CreateProjectSelfService
# and DeleteProjectSelfService below, and their entries in TenantsTable.Meta.
# Everything else is an unmodified copy of the upstream file, kept whole
# (rather than monkeypatching the class from outside it) so a diff against
# the real upstream file shows exactly those additions.

from django.conf import settings
from django.template import defaultfilters as filters
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from horizon import forms
from horizon import tables

from openstack_dashboard import api
from openstack_dashboard import policy
from openstack_dashboard.usage import quotas

from project_selfservice_dashboard import facade


class RescopeTokenToProject(tables.LinkAction):
    name = "rescope"
    verbose_name = _("Set as Active Project")
    url = "switch_tenants"

    def allowed(self, request, project):
        # allow rescoping token to any project the user has a role on,
        # authorized_tenants, and that they are not currently scoped to
        return next((True for proj in request.user.authorized_tenants
                     if proj.id == project.id and
                     project.id != request.user.project_id and
                     project.enabled), False)

    def get_link_url(self, project):
        # redirects to the switch_tenants url which then will redirect
        # back to this page
        dash_url = reverse("horizon:identity:projects:index")
        base_url = reverse(self.url, args=[project.id])
        param = urlencode({"next": dash_url})
        return "?".join([base_url, param])


# The stock "Manage Members" action (UpdateMembersLink, linking to
# UpdateProjectView's update_members step) was removed here -- not just
# hidden -- after being found live to be actively misleading for this
# deployment's group-based persona system, not merely admin-gated wrong.
# Its underlying data source, api.keystone.get_project_users_roles(), calls
# role_assignments_list(request, project=project) with Horizon's own
# default effective=False, which only ever sees *direct* per-user role
# grants. Every DCN persona (reconcile-iam-dcn.sh) grants roles to a
# *group*, never directly to a user, so this workflow showed every real
# federated user (confirmed live with jangwon.lee@dcn.ssu.ac.kr) with zero
# roles checked regardless of their actual access -- and because Keystone's
# grant/revoke API only operates on direct assignments, checking or
# unchecking a box here could never correctly reflect or change a group-
# derived permission anyway (unchecking one silently revokes nothing,
# checking an already-effectively-held role just adds a redundant direct
# grant). Patching the display to effective=True would have looked more
# correct while making the round-trip semantics worse, not better, since
# the edit side still only understands direct grants. See "New permission
# tier: self-service project lifecycle" in the IAM hardening doc for the
# project-facade-backed replacement below (ManageMembersSelfService),
# which reads real effective membership via /users/{id}/groups and
# performs every grant/revoke itself -- a full, correct superset of what
# this stock action was ever able to offer here, so removing it in favor
# of that one tool is a net simplification, not a lost capability.


class UpdateGroupsLink(tables.LinkAction):
    name = "groups"
    verbose_name = _("Modify Groups")
    url = "horizon:identity:projects:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (("identity", "identity:list_groups"),)

    def allowed(self, request, project):
        if settings.OPENSTACK_KEYSTONE_MULTIDOMAIN_SUPPORT:
            # domain admin or cloud admin = True
            # project admin or member = False
            return api.keystone.is_domain_admin(request)
        return super().allowed(request, project)

    def get_link_url(self, project):
        step = 'update_group_members'
        base_url = reverse(self.url, args=[project.id])
        param = urlencode({"step": step})
        return "?".join([base_url, param])


class UsageLink(tables.LinkAction):
    name = "usage"
    verbose_name = _("View Usage")
    url = "horizon:identity:projects:usage"
    icon = "stats"
    policy_rules = (("compute", "os_compute_api:os-simple-tenant-usage:show"),)

    def allowed(self, request, project):
        return (request.user.is_superuser and
                api.base.is_service_enabled(request, 'compute'))


class CreateProject(tables.LinkAction):
    name = "create"
    verbose_name = _("Create Project")
    url = "horizon:identity:projects:create"
    classes = ("ajax-modal",)
    icon = "plus"
    policy_rules = (('identity', 'identity:create_project'),)

    def allowed(self, request, project):
        if settings.OPENSTACK_KEYSTONE_MULTIDOMAIN_SUPPORT:
            # domain admin or cloud admin = True
            # project admin or member = False
            return api.keystone.is_domain_admin(request)
        return api.keystone.keystone_can_edit_project()


class CreateProjectSelfService(tables.LinkAction):
    name = "create_selfservice"
    verbose_name = _("Create Project (Self-Service)")
    url = "horizon:identity:projects:create_selfservice"
    classes = ("ajax-modal",)
    icon = "plus"

    def allowed(self, request, project):
        # Deliberately unconditional (always shown), not mutually
        # exclusive with the native CreateProject action above. An earlier
        # pass tried inverting is_domain_admin(request) (the native
        # action's own real per-user gate in this deployment, since
        # OPENSTACK_KEYSTONE_MULTIDOMAIN_SUPPORT = True here) to show
        # exactly one button per user -- but found live that
        # is_domain_admin() itself is effectively always True in this
        # deployment: it checks Horizon-side policy rule
        # "admin_and_matching_domain_id", which is not defined anywhere in
        # /etc/openstack-dashboard/default_policies/keystone.yaml, and
        # openstack_auth.policy's own check() intentionally fails open for
        # undefined rules ("If a rule is removed, then the default rule is
        # used. We don't want to block all actions because the operator
        # did not fully understand the implication of editing the policy
        # file."). That means the *native* Create Project button is
        # already effectively visible to every logged-in user here too --
        # a pre-existing platform quirk, out of scope to fix as part of
        # this feature. Trying to achieve mutual exclusion against a gate
        # that isn't actually restrictive just adds fragile complexity for
        # no real benefit, so this button is simply always shown instead.
        # None of this affects real authorization either way:
        # project-facade independently requires the project-creator domain
        # role and rejects anyone lacking it with a clear message on
        # submit, regardless of what buttons are visible. See "Authority
        # boundaries" in the IAM hardening doc: UI visibility is never
        # treated as authorization.
        return True


class ManageMembersSelfService(tables.LinkAction):
    name = "manage_members_selfservice"
    # Plain "Manage Members" -- the "(Self-Service)" qualifier this label
    # originally carried made sense only while it stood alongside the
    # native UpdateMembersLink action (removed above, see that comment for
    # why); now that this is the *only* member-management entry point in
    # this table, keeping the qualifier would just read as an unexplained
    # oddity next to a plain "Manage Members" everyone expects.
    verbose_name = _("Manage Members")
    url = "horizon:identity:projects:manage_members_selfservice"
    icon = "pencil"

    def allowed(self, request, project):
        # Same reasoning as CreateProjectSelfService above -- always shown;
        # project-facade requires the caller to actually be admin on this
        # specific project before it lets them add/remove anyone, and
        # refuses to remove the project's last admin.
        return True

    def get_link_url(self, project):
        return reverse(self.url, args=[project.id])


class UpdateProject(policy.PolicyTargetMixin, tables.LinkAction):
    name = "update"
    verbose_name = _("Edit Project")
    url = "horizon:identity:projects:update"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (('identity', 'identity:update_project'),)
    policy_target_attrs = (("target.project.domain_id", "domain_id"),)

    def allowed(self, request, project):
        if settings.OPENSTACK_KEYSTONE_MULTIDOMAIN_SUPPORT:
            # domain admin or cloud admin = True
            # project admin or member = False
            return api.keystone.is_domain_admin(request)
        return api.keystone.keystone_can_edit_project()


class ModifyQuotas(tables.LinkAction):
    name = "quotas"
    verbose_name = _("Modify Quotas")
    url = "horizon:identity:projects:update_quotas"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (('compute', "os_compute_api:os-quota-sets:update"),)

    def allowed(self, request, datum):
        return (api.keystone.is_cloud_admin(request) and
                quotas.enabled_quotas(request))

    def get_link_url(self, project):
        step = 'update_quotas'
        base_url = reverse(self.url, args=[project.id])
        param = urlencode({"step": step})
        return "?".join([base_url, param])


class DeleteTenantsAction(policy.PolicyTargetMixin, tables.DeleteAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Delete Project",
            "Delete Projects",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Deleted Project",
            "Deleted Projects",
            count
        )

    policy_rules = (("identity", "identity:delete_project"),)
    policy_target_attrs = (("target.project.domain_id", "domain_id"),)

    def allowed(self, request, project):
        if (settings.OPENSTACK_KEYSTONE_MULTIDOMAIN_SUPPORT and
                not api.keystone.is_domain_admin(request)):
            return False
        return api.keystone.keystone_can_edit_project()

    def delete(self, request, obj_id):
        api.keystone.tenant_delete(request, obj_id)

    def handle(self, table, request, obj_ids):
        response = super().handle(table, request, obj_ids)
        return response


class DeleteProjectSelfService(tables.DeleteAction):
    name = "delete_selfservice"

    @staticmethod
    def action_present(count):
        return ngettext_lazy("Delete Project", "Delete Projects", count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy("Deleted Project", "Deleted Projects", count)

    def allowed(self, request, project):
        # Deliberately unconditional -- see CreateProjectSelfService.allowed()
        # above for why attempting mutual exclusion against the native
        # DeleteTenantsAction was abandoned (its own real gate,
        # is_domain_admin(request), was found live to be effectively
        # always-True in this deployment due to an undefined Horizon
        # policy rule, so the native button is already visible to everyone
        # here too). project-facade re-checks that the caller is admin on
        # this exact project and that it isn't a domain's protected admin
        # project (options.immutable) before doing anything, on every
        # request, independent of this check.
        return True

    def delete(self, request, obj_id):
        facade.delete_project(request, obj_id)


class LeaveProjectSelfService(tables.LinkAction):
    name = "leave_selfservice"
    verbose_name = _("Leave Project")
    url = "horizon:identity:projects:leave_selfservice"
    classes = ("ajax-modal",)
    icon = "remove"

    def allowed(self, request, project):
        # Unconditional, same reasoning as every other self-service action
        # in this table -- project-facade's own leave_project endpoint is
        # the real gate (refuses only if the caller is this project's last
        # admin); showing the button to everyone and letting the facade's
        # own response explain a refusal is simpler than trying to predict
        # "are you the last admin" here just to hide a button.
        return True

    def get_link_url(self, project):
        return reverse(self.url, args=[project.id])


class MyAccessLink(tables.LinkAction):
    name = "my_access"
    verbose_name = _("My Access")
    url = "horizon:identity:projects:my_access"
    icon = "list"

    def allowed(self, request, project):
        # Unconditional and not row-scoped -- see CreateProjectSelfService
        # above for the general reasoning. This one genuinely has nothing
        # to gate on: it's always the caller's own access.
        return True


class DomainProjectsOverviewLink(tables.LinkAction):
    name = "domain_projects_overview"
    verbose_name = _("Domain Projects Overview")
    url = "horizon:identity:projects:domain_projects_overview"
    icon = "list"

    def allowed(self, request, project):
        # Unconditional, same reasoning as every other self-service
        # action in this table -- project-facade's own domain-admin
        # check on GET /v1/domain-projects-overview is the real gate.
        return True


class AuditLogSelfService(tables.LinkAction):
    name = "audit_log_selfservice"
    verbose_name = _("Audit Log")
    url = "horizon:identity:projects:audit_log_selfservice"
    icon = "list"

    def allowed(self, request, project):
        # Unconditional, same reasoning as every other self-service action
        # in this table -- project-facade's own audit-log endpoint is the
        # real gate (admin on this project or its domain, same check as
        # Manage Members); a non-admin who follows this link sees that
        # endpoint's own error message rather than an empty or misleading
        # table.
        return True

    def get_link_url(self, project):
        return reverse(self.url, args=[project.id])


class TenantFilterAction(tables.FilterAction):
    filter_type = "server"
    filter_choices = (('name', _("Project Name ="), True),
                      ('id', _("Project ID ="), True),
                      ('enabled', _("Enabled ="), True, _('e.g. Yes/No')))


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, project_id):
        project_info = api.keystone.tenant_get(request, project_id,
                                               admin=True)
        return project_info


class TenantsTable(tables.DataTable):
    name = tables.WrappingColumn('name', verbose_name=_('Name'),
                                 link=("horizon:identity:projects:detail"),
                                 form_field=forms.CharField(max_length=64))
    description = tables.Column(lambda obj: getattr(obj, 'description', None),
                                verbose_name=_('Description'),
                                form_field=forms.CharField(
                                    widget=forms.Textarea(attrs={'rows': 4}),
                                    required=False))
    id = tables.Column('id', verbose_name=_('Project ID'))
    domain_name = tables.Column(
        'domain_name', verbose_name=_('Domain Name'))
    enabled = tables.Column('enabled', verbose_name=_('Enabled'), status=True,
                            filters=(filters.yesno, filters.capfirst),
                            form_field=forms.BooleanField(
                                label=_('Enabled'),
                                required=False))

    def get_project_detail_link(self, project):
        # this method is an ugly monkey patch, needed because
        # the column link method does not provide access to the request
        if policy.check((("identity", "identity:get_project"),),
                        self.request, target={"project": project}):
            return reverse("horizon:identity:projects:detail",
                           args=(project.id,))
        return None

    def __init__(self, request, data=None, needs_form_wrapper=None, **kwargs):
        super().__init__(request, data=data,
                         needs_form_wrapper=needs_form_wrapper, **kwargs)
        # see the comment above about ugly monkey patches
        self.columns['name'].get_link_url = self.get_project_detail_link

    class Meta(object):
        name = "tenants"
        verbose_name = _("Projects")
        row_class = UpdateRow
        row_actions = (UpdateGroupsLink, UpdateProject,
                       UsageLink, ModifyQuotas, DeleteTenantsAction,
                       DeleteProjectSelfService, ManageMembersSelfService,
                       AuditLogSelfService, LeaveProjectSelfService,
                       RescopeTokenToProject)
        table_actions = (TenantFilterAction, CreateProject,
                         CreateProjectSelfService, MyAccessLink,
                         DomainProjectsOverviewLink, DeleteTenantsAction)
        pagination_param = "tenant_marker"
