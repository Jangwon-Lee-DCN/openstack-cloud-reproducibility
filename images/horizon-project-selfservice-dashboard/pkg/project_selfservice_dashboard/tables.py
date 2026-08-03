from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from horizon import tables

from . import facade


class AddMember(tables.LinkAction):
    name = "add_member"
    verbose_name = _("Add Member")
    url = "horizon:identity:projects:manage_members_selfservice_add"
    classes = ("ajax-modal",)
    icon = "plus"

    def get_link_url(self, datum=None):
        return reverse(self.url, args=[self.table.kwargs["project_id"]])


class RemoveMember(tables.DeleteAction):
    name = "remove_member"

    @staticmethod
    def action_present(count):
        return ngettext_lazy("Remove Member", "Remove Members", count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy("Removed Member", "Removed Members", count)

    def allowed(self, request, member):
        # project-facade itself re-checks that the caller is admin on this
        # project and refuses to remove the project's last remaining admin,
        # on every request -- this is a usability nicety only.
        return True

    def delete(self, request, obj_id):
        facade.remove_member(request, self.table.kwargs["project_id"], obj_id)


class MembersTable(tables.DataTable):
    username = tables.Column("username", verbose_name=_("Username"))
    roles = tables.Column("roles", verbose_name=_("Roles"))

    class Meta:
        name = "members"
        verbose_name = _("Project Members")
        table_actions = (AddMember,)
        row_actions = (RemoveMember,)
