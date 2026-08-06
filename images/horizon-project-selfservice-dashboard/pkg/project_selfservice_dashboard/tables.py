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


class AddProjectGroup(tables.LinkAction):
    name = "add_project_group"
    verbose_name = _("Add Group")
    url = "horizon:identity:projects:add_project_group"
    classes = ("ajax-modal",)
    icon = "plus"

    def get_link_url(self, datum=None):
        return reverse(self.url, args=[self.table.kwargs["project_id"]])


class ChangeProjectGroupRoles(tables.LinkAction):
    name = "change_project_group_roles"
    verbose_name = _("Change Roles")
    url = "horizon:identity:projects:change_project_group_roles"
    classes = ("ajax-modal",)
    icon = "pencil"

    def get_link_url(self, group):
        return reverse(self.url, args=[self.table.kwargs["project_id"], group.id])


class RemoveProjectGroup(tables.DeleteAction):
    name = "remove_project_group"

    @staticmethod
    def action_present(count):
        return ngettext_lazy("Remove Group", "Remove Groups", count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy("Removed Group", "Removed Groups", count)

    def delete(self, request, obj_id):
        facade.remove_project_group(request, self.table.kwargs["project_id"], obj_id)


class ProjectGroupsTable(tables.DataTable):
    name = tables.Column("name", verbose_name=_("Group"))
    roles = tables.Column("roles", verbose_name=_("Roles"))

    class Meta:
        name = "project_groups"
        verbose_name = _("Group Assignments")
        table_actions = (AddProjectGroup,)
        row_actions = (ChangeProjectGroupRoles, RemoveProjectGroup)


def _quota_limit(row):
    return _("Unlimited") if row.limit < 0 else row.limit


def _quota_usage(row):
    if row.limit < 0:
        return str(row.used)
    return _("%(used)s of %(limit)s (%(percent)s%%)") % {
        "used": row.used, "limit": row.limit, "percent": row.percent,
    }


class QuotaUsageTable(tables.DataTable):
    service = tables.Column("service", verbose_name=_("Service"))
    resource = tables.Column("resource", verbose_name=_("Resource"))
    usage = tables.Column(_quota_usage, verbose_name=_("Usage / Limit"))
    state = tables.Column(
        "state", verbose_name=_("State"), status=True,
        status_choices=(("ok", True), ("unlimited", True), ("warning", None), ("exhausted", False)),
    )

    class Meta:
        name = "quota_usage"
        verbose_name = _("Quota & Usage")
        multi_select = False


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


class ManageApplicationCredentialsLink(tables.LinkAction):
    name = "application_credentials"
    verbose_name = _("Application Credentials")
    url = "horizon:identity:projects:application_credentials"
    icon = "key"


class MyAccessTable(tables.DataTable):
    project_name = tables.Column("project_name", verbose_name=_("Project"))
    project_id = tables.Column("project_id", verbose_name=_("Project ID"))
    roles = tables.Column("roles", verbose_name=_("Your Roles"))

    class Meta:
        name = "my_access"
        verbose_name = _("My Access")
        multi_select = False
        table_actions = (ManageApplicationCredentialsLink,)
        row_actions = (ViewProjectMembers,)


class ManageProjectTags(tables.LinkAction):
    name = "manage_project_tags"
    verbose_name = _("Manage Tags")
    url = "horizon:identity:projects:manage_project_tags"
    classes = ("ajax-modal",)
    icon = "tag"

    def get_link_url(self, datum):
        return reverse(self.url, args=[datum.project_id])


class DomainProjectsOverviewTable(tables.DataTable):
    project_name = tables.Column("project_name", verbose_name=_("Project"))
    project_id = tables.Column("project_id", verbose_name=_("Project ID"))
    admins = tables.Column("admins", verbose_name=_("Admin(s)"))
    member_count = tables.Column("member_count", verbose_name=_("Members"))
    # Keystone's native project tags -- see project-facade app.py's
    # list_project_tags/set_project_tags. Their main consumer is role
    # bundles' optional required_tag (see RoleBundlesTable below), but
    # shown here since this is the one page a domain admin sees every
    # project in the domain at once.
    tags = tables.Column("tags", verbose_name=_("Tags"), empty_value=_("no tags"))
    last_activity = tables.Column(
        "last_activity",
        verbose_name=_("Last Self-Service Activity"),
        empty_value=_("no recent activity"),
    )

    class Meta:
        name = "domain_projects_overview"
        verbose_name = _("Domain Projects Overview")
        multi_select = False
        row_actions = (ViewProjectMembers, ManageProjectTags)


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
    # Optional permission boundary -- see project-facade app.py's
    # _expand_role_bundles. Empty for every bundle created before this
    # field existed, same as description defaulting to "".
    required_tag = tables.Column(
        "required_tag", verbose_name=_("Requires Project Tag"), empty_value="-"
    )

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


class CreateApplicationCredential(tables.LinkAction):
    name = "create_application_credential"
    verbose_name = _("Create Application Credential")
    url = "horizon:identity:projects:create_application_credential"
    classes = ("ajax-modal",)
    icon = "plus"

    def allowed(self, request, datum=None):
        selected = self.table.kwargs.get("project_id")
        return not selected or selected == request.user.project_id


class RevokeApplicationCredential(tables.DeleteAction):
    name = "revoke_application_credential"

    @staticmethod
    def action_present(count):
        return ngettext_lazy("Revoke Credential", "Revoke Credentials", count)

    @staticmethod
    def action_past(count):
        return ngettext_lazy("Revoked Credential", "Revoked Credentials", count)

    def allowed(self, request, credential):
        # Unconditional -- project-facade forwards this straight to
        # Keystone's own self-only application-credentials API, which
        # already refuses to delete anything not owned by the caller.
        return True

    def delete(self, request, obj_id):
        facade.delete_application_credential(request, obj_id)


class ApplicationCredentialsTable(tables.DataTable):
    name = tables.Column("name", verbose_name=_("Name"))
    project_id = tables.Column("project_id", verbose_name=_("Project ID"))
    roles = tables.Column("roles", verbose_name=_("Roles"))
    expires_at = tables.Column("expires_at", verbose_name=_("Expires"), empty_value="-")
    status = tables.Column(
        "status",
        verbose_name=_("Status"),
        status=True,
        status_choices=(("active", True), ("expiring-soon", None), ("expired", False)),
    )

    class Meta:
        name = "application_credentials"
        verbose_name = _("My Application Credentials")
        multi_select = False
        table_actions = (CreateApplicationCredential,)
        row_actions = (RevokeApplicationCredential,)
