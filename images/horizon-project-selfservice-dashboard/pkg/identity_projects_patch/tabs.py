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

    table_classes = (selfservice_tables.ProjectGroupsTable,)
    name = _("Group Assignments")
    slug = "groups"
    template_name = "horizon/common/_detail_table.html"
    preload = False

    def __init__(self, tab_group, request):
        tab_group.kwargs["project_id"] = tab_group.kwargs["project"].id
        super().__init__(tab_group, request)

    def get_project_groups_data(self):
        project = self.tab_group.kwargs["project"]
        try:
            return [
                SimpleNamespace(
                    id=item["group_id"], name=item["name"], roles=", ".join(item["roles"])
                )
                for item in facade.project_groups(self.request, project.id)["assignments"]
            ]
        except facade.FacadeError:
            exceptions.handle(self.request, _("Unable to display project group assignments."))
            return []


class ProjectDetailTabs(tabs.DetailTabsGroup):
    slug = "project_details"
    tabs = (OverviewTab, MembersTab, GroupsTab)
