from types import SimpleNamespace

from django.http import HttpResponse
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from horizon import exceptions
from horizon import forms as horizon_forms
from horizon import messages
from horizon import tables as horizon_tables

from . import facade
from . import forms
from . import tables

# list_members() returns every *effective* role, implied roles included
# (e.g. "admin" also implies "manager"). "manager" itself is never
# directly grantable/settable (see project_selfservice_dashboard.forms.
# ROLE_CHOICES / project-facade's ALLOWED_MEMBER_ROLES), so it's filtered
# out when pre-selecting a Change Role form's current checkboxes.
SETTABLE_ROLES = {"admin", "member", "reader", "network-operator", "security-operator", "load-balancer_admin", "monitoring"}


class CreateProjectSelfServiceView(horizon_forms.ModalFormView):
    """Reached from a "Create Project (Self-Service)" action added to the
    stock Identity > Projects table (see identity_projects_patch/tables.py)
    -- deliberately a separate, small ModalFormView rather than extending
    that panel's native multi-step CreateProjectView workflow, since it
    only needs a name and description; project-facade handles the rest
    (domain, ownership grant) itself. See docs/proposals/iam-hardening/
    README.md, "New permission tier: self-service project lifecycle".
    """

    form_class = forms.CreateProjectForm
    template_name = "project_selfservice/create.html"
    success_url = reverse_lazy("horizon:identity:projects:index")
    cancel_url = reverse_lazy("horizon:identity:projects:index")
    page_title = _("Create Project (Self-Service)")
    submit_label = _("Create Project")
    submit_url = reverse_lazy("horizon:identity:projects:create_selfservice")


class ManageMembersSelfServiceView(horizon_tables.DataTableView):
    """Reached from a "Manage Members (Self-Service)" row action added to
    the same stock table. Lists the calling project's members and lets its
    admin add/remove them -- project-facade re-checks the caller is admin
    on this exact project (and refuses to remove its last admin) on every
    request, independent of anything this view shows or hides.
    """

    table_class = tables.MembersTable
    page_title = _("Project Members")

    def get_data(self):
        project_id = self.kwargs["project_id"]
        try:
            members = facade.list_members(self.request, project_id)
        except facade.FacadeError as exc:
            messages.error(self.request, str(exc))
            return []
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve project members."))
            return []
        # DataTable.get_object_id() (used for every row action) does
        # datum.id via plain attribute access -- a dict works fine for
        # ordinary Column lookups (Column.get_raw_data() special-cases
        # Mapping objects) but not for that, so use a simple attribute-
        # holding object instead of a dict here.
        return [
            SimpleNamespace(id=m["user_id"], username=m["username"], roles=", ".join(sorted(m["roles"])))
            for m in members
        ]


class AddMemberView(horizon_forms.ModalFormView):
    form_class = forms.AddMemberForm
    template_name = "project_selfservice/add_member.html"
    page_title = _("Add Member")
    submit_label = _("Add Member")

    def get_success_url(self):
        return reverse("horizon:identity:projects:manage_members_selfservice", args=[self.kwargs["project_id"]])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["submit_url"] = reverse(
            "horizon:identity:projects:manage_members_selfservice_add", args=[self.kwargs["project_id"]]
        )
        context["cancel_url"] = self.get_success_url()
        return context

    def get_initial(self):
        return {"project_id": self.kwargs["project_id"]}


class BulkAddMemberView(horizon_forms.ModalFormView):
    form_class = forms.BulkAddMemberForm
    template_name = "project_selfservice/bulk_add_member.html"
    page_title = _("Bulk Invite Members")
    submit_label = _("Add Members")

    def get_success_url(self):
        return reverse("horizon:identity:projects:manage_members_selfservice", args=[self.kwargs["project_id"]])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["submit_url"] = reverse(
            "horizon:identity:projects:manage_members_selfservice_bulk_add", args=[self.kwargs["project_id"]]
        )
        context["cancel_url"] = self.get_success_url()
        return context

    def get_initial(self):
        return {"project_id": self.kwargs["project_id"]}


class ChangeMemberRoleView(horizon_forms.ModalFormView):
    form_class = forms.ChangeMemberRoleForm
    template_name = "project_selfservice/add_member.html"
    page_title = _("Change Member Role")
    submit_label = _("Change Role")

    def get_success_url(self):
        return reverse("horizon:identity:projects:manage_members_selfservice", args=[self.kwargs["project_id"]])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["submit_url"] = reverse(
            "horizon:identity:projects:manage_members_selfservice_change_role",
            args=[self.kwargs["project_id"], self.kwargs["user_id"]],
        )
        context["cancel_url"] = self.get_success_url()
        return context

    def get_initial(self):
        project_id = self.kwargs["project_id"]
        user_id = self.kwargs["user_id"]
        username = ""
        current_roles = ["member"]
        try:
            for m in facade.list_members(self.request, project_id):
                if m["user_id"] == user_id:
                    username = m["username"]
                    current_roles = [r for r in m["roles"] if r in SETTABLE_ROLES] or ["member"]
                    break
        except facade.FacadeError as exc:
            messages.error(self.request, str(exc))
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve this member's current roles."))
        return {"project_id": project_id, "username": username, "roles": current_roles}


class TransferOwnershipView(horizon_forms.ModalFormView):
    """Reached from a "Transfer Ownership" row action on the Members
    table -- promotes that row's user to admin and demotes the caller to
    member in one request. See project-facade app.py's
    transfer_ownership for why this is the atomic alternative to the
    previous two-step change-role-then-leave process."""

    form_class = forms.TransferOwnershipForm
    template_name = "project_selfservice/transfer_ownership.html"
    page_title = _("Transfer Ownership")
    submit_label = _("Transfer Ownership")

    def get_success_url(self):
        return reverse("horizon:identity:projects:manage_members_selfservice", args=[self.kwargs["project_id"]])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["submit_url"] = reverse(
            "horizon:identity:projects:manage_members_selfservice_transfer_ownership",
            args=[self.kwargs["project_id"], self.kwargs["user_id"]],
        )
        context["cancel_url"] = self.get_success_url()
        return context

    def get_initial(self):
        project_id = self.kwargs["project_id"]
        user_id = self.kwargs["user_id"]
        username = ""
        try:
            for m in facade.list_members(self.request, project_id):
                if m["user_id"] == user_id:
                    username = m["username"]
                    break
        except facade.FacadeError as exc:
            messages.error(self.request, str(exc))
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve this member's username."))
        return {"project_id": project_id, "username": username}


class AuditLogView(horizon_tables.DataTableView):
    """Read-only trail of self-service actions taken against this project
    (including denied attempts), sourced from project-facade's own
    request logs via Loki -- see facade.audit_log and project-facade
    app.py's project_audit_log for where this actually comes from. Same
    "admin on this project or its domain" gate as Manage Members; a
    non-admin hitting this URL directly gets project-facade's own 403
    surfaced as a page error, same pattern as every other view here.
    """

    table_class = tables.AuditLogTable
    page_title = _("Audit Log")

    def get_data(self):
        project_id = self.kwargs["project_id"]
        try:
            entries = facade.audit_log(self.request, project_id)
        except facade.FacadeError as exc:
            messages.error(self.request, str(exc))
            return []
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve this project's audit log."))
            return []
        # DataTable.get_object_id() does datum.id via plain attribute
        # access (see ManageMembersSelfServiceView.get_data() above for
        # the same issue) -- synthesize one, since a Loki log line has no
        # natural id of its own and (timestamp, message) together are
        # unique in practice.
        return [
            SimpleNamespace(id=f"{e['timestamp']}-{i}", **e)
            for i, e in enumerate(entries)
        ]


def export_audit_log_csv(request, project_id):
    """Plain function view, not a class -- mirrors export_audit_csv in the
    VPC dashboard (openstack_vpc_dashboard.dashboards.project.vpc.vpcs.
    views), the established pattern in this deployment for a download-a-
    file action rather than a page render. project-facade's own admin-or-
    domain-admin gate on the audit-log endpoint is what actually protects
    this -- a non-admin's request comes back as project-facade's own error
    message, still shown to the user, not the CSV file."""
    try:
        content = facade.export_audit_log_csv(request, project_id)
    except facade.FacadeError as exc:
        messages.error(request, str(exc))
        content = b""
    response = HttpResponse(content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="project-{project_id}-audit-log.csv"'
    return response


class LeaveProjectView(horizon_forms.ModalFormView):
    """Lets any member remove themselves from a project, no admin rights
    needed -- see project-facade app.py's leave_project for why this is a
    deliberately different authorization path from every other member-
    management action in this app. Reached from a "Leave Project" row
    action on the same stock Identity > Projects table.
    """

    form_class = forms.LeaveProjectForm
    template_name = "project_selfservice/leave_project.html"
    page_title = _("Leave Project")
    submit_label = _("Leave Project")
    success_url = reverse_lazy("horizon:identity:projects:index")

    def get_success_url(self):
        return str(self.success_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["submit_url"] = reverse(
            "horizon:identity:projects:leave_selfservice", args=[self.kwargs["project_id"]]
        )
        context["cancel_url"] = self.get_success_url()
        return context

    def get_initial(self):
        return {"project_id": self.kwargs["project_id"]}
