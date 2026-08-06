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
    # "project-facade" (this project's own create/update/member/etc.
    # actions) or "vpc-facade" (its networking/VPC resource history for
    # the same project) -- see project-facade app.py's
    # _vpc_facade_audit_entries for how the two get merged into one
    # table.
    source = tables.Column("source", verbose_name=_("Source"))
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


class RoleBundlesAuditLogTable(AuditLogTable):
    """Same columns as AuditLogTable, minus ExportAuditLogCSV -- that
    action's link URL needs a project_id table kwarg
    (identity_projects_patch:audit_log_selfservice_export), which this
    table's view (role bundles are domain-scoped, not project-scoped)
    never has; reusing AuditLogTable's Meta unmodified would raise a
    KeyError the moment the page tried to render that button."""

    class Meta(AuditLogTable.Meta):
        name = "role_bundles_audit_log"
        verbose_name = _("Role Bundle History")
        table_actions = ()


# Shared by MyAccessTable and DomainProjectsOverviewTable below -- both
# tables' rows carry a project_id, and "go manage this project's members"
# is the same jump-off point from either one. project-facade's own
# _authorize_member_admin re-checks the caller actually has access on
# arrival, same as every other self-service link in this app.
class ViewProjectMembers(tables.LinkAction):
    name = "view_project_members"
    verbose_name = _("Manage Members")
    url = "horizon:identity:projects:manage_members_selfservice"
    icon = "pencil"

    def get_link_url(self, datum):
        return reverse(self.url, args=[datum.project_id])


class MyAccessTable(tables.DataTable):
    project_name = tables.Column("project_name", verbose_name=_("Project"))
    project_id = tables.Column("project_id", verbose_name=_("Project ID"))
    roles = tables.Column("roles", verbose_name=_("Your Roles"))

    class Meta:
        name = "my_access"
        verbose_name = _("My Access")
        multi_select = False
        row_actions = (ViewProjectMembers,)


class DomainProjectsOverviewTable(tables.DataTable):
    project_name = tables.Column("project_name", verbose_name=_("Project"))
    project_id = tables.Column("project_id", verbose_name=_("Project ID"))
    admins = tables.Column("admins", verbose_name=_("Admin(s)"))
    member_count = tables.Column("member_count", verbose_name=_("Members"))
    last_activity = tables.Column(
        "last_activity",
        verbose_name=_("Last Self-Service Activity"),
        empty_value=_("no recent activity"),
    )

    class Meta:
        name = "domain_projects_overview"
        verbose_name = _("Domain Projects Overview")
        multi_select = False
        row_actions = (ViewProjectMembers,)


class CreateRoleBundle(tables.LinkAction):
    name = "create_role_bundle"
    verbose_name = _("Create Role Bundle")
    url = "horizon:identity:projects:create_role_bundle"
    classes = ("ajax-modal",)
    icon = "plus"


class RoleBundlesAuditLogLink(tables.LinkAction):
    name = "role_bundles_audit_log"
    verbose_name = _("History")
    url = "horizon:identity:projects:role_bundles_audit_log"
    icon = "list"


class DeleteRoleBundle(tables.DeleteAction):
    name = "delete_role_bundle"

    @staticmethod
    def action_present(count):
        return ngettext_lazy("Delete Role Bundle", "Delete Role Bundles", count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy("Deleted Role Bundle", "Deleted Role Bundles", count)

    def allowed(self, request, bundle):
        # Unconditional -- project-facade's own domain-admin check on
        # DELETE /v1/role-bundles/<name> is the real gate.
        return True

    def delete(self, request, obj_id):
        facade.delete_role_bundle(request, obj_id)


class RoleBundlesTable(tables.DataTable):
    name = tables.Column("name", verbose_name=_("Bundle Name"))
    description = tables.Column("description", verbose_name=_("Description"))
    roles = tables.Column("roles", verbose_name=_("Expands To"))

    class Meta:
        name = "role_bundles"
        verbose_name = _("Role Bundles")
        table_actions = (CreateRoleBundle, RoleBundlesAuditLogLink)
        row_actions = (DeleteRoleBundle,)


class SimulateAccessTable(tables.DataTable):
    action = tables.Column("action", verbose_name=_("Action"))
    allowed = tables.Column(
        "allowed",
        verbose_name=_("Can You Do This?"),
        status=True,
        status_choices=(("Yes", True), ("No", False)),
    )
    reason = tables.Column("reason", verbose_name=_("Why"), empty_value="")

    class Meta:
        name = "simulate_access"
        verbose_name = _("What Can I Do Here?")
        multi_select = False
