from django import forms
from django.utils.translation import gettext_lazy as _

from horizon import exceptions
from horizon import forms as horizon_forms
from horizon import messages

from project_selfservice_dashboard import facade


class CreateProjectForm(horizon_forms.SelfHandlingForm):
    name = forms.CharField(label=_("Project Name"), max_length=64)
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def handle(self, request, data):
        try:
            project = facade.create_project(request, data["name"], data.get("description", ""))
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to create project."))
            return False
        messages.success(
            request,
            _('Project "%s" was created. You are now its administrator.') % project["name"],
        )
        return project


class AddMemberForm(horizon_forms.SelfHandlingForm):
    username = forms.CharField(label=_("Username"))
    role = forms.ChoiceField(
        label=_("Role"),
        choices=[("member", _("Member")), ("reader", _("Reader")), ("admin", _("Admin"))],
        initial="member",
    )

    def handle(self, request, data):
        project_id = self.initial["project_id"]
        try:
            member = facade.add_member(request, project_id, data["username"], data["role"])
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to add member."))
            return False
        messages.success(
            request,
            _('Added "%(username)s" to this project as %(role)s.') % member,
        )
        return member
