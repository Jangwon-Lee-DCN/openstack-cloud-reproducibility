from types import SimpleNamespace

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

# Order to search a member's effective roles in for the "current role" a
# Change Role form should pre-select. list_members() returns every
# effective role (implied roles included, e.g. "admin" also implies
# manager/member/reader), so this picks the highest one that's actually a
# settable member-tier role.
ROLE_PRIORITY = ("admin", "member", "reader")


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
        current_role = "member"
        try:
            for m in facade.list_members(self.request, project_id):
                if m["user_id"] == user_id:
                    username = m["username"]
                    current_role = next((r for r in ROLE_PRIORITY if r in m["roles"]), "member")
                    break
        except facade.FacadeError as exc:
            messages.error(self.request, str(exc))
        except Exception:
            exceptions.handle(self.request, _("Unable to retrieve this member's current role."))
        return {"project_id": project_id, "username": username, "role": current_role}
