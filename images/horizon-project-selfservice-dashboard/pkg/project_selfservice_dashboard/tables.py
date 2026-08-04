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


class BulkAddMember(tables.LinkAction):
    name = "bulk_add_member"
    verbose_name = _("Bulk Invite")
    url = "horizon:identity:projects:manage_members_selfservice_bulk_add"
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


class TransferOwnership(tables.LinkAction):
    name = "transfer_ownership"
    verbose_name = _("Transfer Ownership")
    url = "horizon:identity:projects:manage_members_selfservice_transfer_ownership"
    classes = ("ajax-modal",)
    icon = "arrow-right"

    def allowed(self, request, member):
        # Unconditional, same reasoning as every other self-service
        # action in this table -- project-facade's own transfer-ownership
        # endpoint is the real gate (caller must be a current effective
        # admin; can't target yourself). Showing it on every row and
        # letting the facade's response explain a refusal is simpler than
        # trying to predict "am I an admin, is this row not me" here.
        return True

    def get_link_url(self, member):
        return reverse(self.url, args=[self.table.kwargs["project_id"], member.id])


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
        table_actions = (AddMember, BulkAddMember)
        row_actions = (ChangeRole, TransferOwnership, RemoveMember)


class ExportAuditLogCSV(tables.LinkAction):
    name = "audit_log_export"
    verbose_name = _("Export CSV")
    url = "horizon:identity:projects:audit_log_selfservice_export"
    icon = "download"

    def get_link_url(self, datum=None):
        return reverse(self.url, args=[self.table.kwargs["project_id"]])


class AuditLogTable(tables.DataTable):
    timestamp = tables.Column("timestamp", verbose_name=_("Time"))
    action = tables.Column("action", verbose_name=_("Action"))
    # Same denied/allowed distinction project-facade itself logs at --
    # status=True/status_choices renders this as a status-styled
    # (success/danger) value instead of plain text, so a denied attempt
    # is visually distinct in the table.
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
        table_actions = (ExportAuditLogCSV,)
