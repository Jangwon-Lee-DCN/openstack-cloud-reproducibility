"""Project detail tabs adapted to the platform membership contract.

The upstream Users tab is a read-only reconstruction of direct and group
Keystone grants.  The platform previously exposed that beside a separate
Manage Members action backed by project-facade.  This module makes the
authoritative, writable member inventory the project detail tab instead.
"""

from types import SimpleNamespace

from django.conf import settings
from django.utils.translation import gettext_lazy as _

from horizon import exceptions
from horizon import tabs

from openstack_dashboard import api
from openstack_dashboard import policy
from openstack_dashboard.dashboards.identity.projects.groups import tables as groups_tables

from project_selfservice_dashboard import facade
from project_selfservice_dashboard import tables as selfservice_tables


class OverviewTab(tabs.Tab):
    name = _("Overview")
    slug = "overview"
    template_name = "identity/projects/_detail_overview.html"

    def get_context_data(self, request):
        project = self.tab_group.kwargs["project"]
        return {
            "project": project,
            "domain_name": self._get_domain_name(project),
            "extras": self._get_extras(project),
        }

    def _get_domain_name(self, project):
        try:
            if policy.check((("identity", "identity:get_domain"),), self.request):
                return api.keystone.domain_get(self.request, project.domain_id).name
            return api.keystone.get_default_domain(self.request).get("name", "")
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve project domain."))
            return ""

    @staticmethod
    def _get_extras(project):
        return {
            display_key: getattr(project, key, "")
            for key, display_key in settings.PROJECT_TABLE_EXTRA_INFO.items()
        }


class MembersTab(tabs.TableTab):
    """The single project membership inventory and edit entry point."""

    table_classes = (selfservice_tables.MembersTable,)
    name = _("Members")
    slug = "members"
    template_name = "horizon/common/_detail_table.html"
    preload = False

    def __init__(self, tab_group, request):
        # MembersTable's existing actions consume project_id from table
        # kwargs; detail tabs normally carry the project object instead.
        tab_group.kwargs["project_id"] = tab_group.kwargs["project"].id
        super().__init__(tab_group, request)

    def get_memberstable_data(self):
        project = self.tab_group.kwargs["project"]
        try:
            members = facade.list_members(self.request, project.id)
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve project members."))
            return []
        return [
            SimpleNamespace(
                id=member["user_id"],
                username=member["username"],
                roles=", ".join(sorted(member["roles"])),
            )
            for member in members
        ]

class GroupsTab(tabs.TableTab):
    """Advanced group-derived assignments, kept separate from people."""

    table_classes = (groups_tables.GroupsTable,)
    name = _("Group Assignments")
    slug = "groups"
    template_name = "horizon/common/_detail_table.html"
    preload = False

    def get_groupstable_data(self):
        groups_in_project = []
        project = self.tab_group.kwargs["project"]
        try:
            domain_id = project.domain_id
            project_groups_roles = api.keystone.get_project_groups_roles(
                self.request, project=project.id
            )
            roles = api.keystone.role_list(self.request)
            groups = {
                group.id: group
                for group in api.keystone.group_list(self.request, domain=domain_id)
            }
            for group_id, role_ids in project_groups_roles.items():
                if group_id not in groups:
                    continue
                group = groups[group_id]
                group.roles = [role.name for role in roles if role.id in role_ids]
                groups_in_project.append(group)
        except Exception:
            exceptions.handle(self.request, _("Unable to display project group assignments."))
        return groups_in_project


class ProjectDetailTabs(tabs.DetailTabsGroup):
    slug = "project_details"
    tabs = (OverviewTab, MembersTab, GroupsTab)
