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


class ChangeRole(tables.LinkAction):
    name = "change_role"
    verbose_name = _("Change Role")
    url = "horizon:identity:projects:manage_members_selfservice_change_role"
    classes = ("ajax-modal",)
    icon = "pencil"

    def get_link_url(self, datum):
        return reverse(self.url, args=[self.table.kwargs["project_id"], datum.id])


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
        row_actions = (ChangeRole, RemoveMember)


# Same denied/allowed distinction project-facade itself logs at -- shown
# as a status-styled column (get_data_type -> danger/warning/success) so
# a denied attempt is visually distinct in the table, not just a plain
# text value.
_AUDIT_LEVEL_STATUS = {"WARNING": "danger", "ERROR": "danger"}


class AuditLogTable(tables.DataTable):
    timestamp = tables.Column("timestamp", verbose_name=_("Time"))
    action = tables.Column("action", verbose_name=_("Action"))
    level = tables.Column(
        "level",
        verbose_name=_("Result"),
        status=True,
        status_choices=(("INFO", True), ("WARNING", False), ("ERROR", False)),
    )
    message = tables.Column("message", verbose_name=_("Detail"))

    class Meta:
        name = "audit_log"
        verbose_name = _("Audit Log")
        # Loki, not Keystone/project-facade's own DB -- there is nothing
        # here for a project admin to add, edit, or delete; this table is
        # read-only by design (see facade.audit_log's docstring).
        multi_select = False
