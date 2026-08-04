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


# Matches project-facade/app.py's ALLOWED_MEMBER_ROLES. The first three
# are the base access tiers; the rest are the platform's additive marker
# roles (reconcile-iam-dcn.sh) -- a member typically wants a base tier
# plus zero or more of these together (e.g. Member + Network Operator),
# since the marker roles alone don't grant ordinary project CRUD in
# vpc-facade's own authorization classes. This form doesn't enforce that
# combination; it just lets the project admin pick any set.
ROLE_CHOICES = [
    ("admin", _("Admin")),
    ("member", _("Member")),
    ("reader", _("Reader")),
    ("network-operator", _("Network Operator")),
    ("security-operator", _("Security Operator")),
    ("load-balancer_admin", _("Load Balancer Operator")),
    ("monitoring", _("Monitoring")),
]


class AddMemberForm(horizon_forms.SelfHandlingForm):
    username = forms.CharField(label=_("Username"))
    roles = forms.MultipleChoiceField(
        label=_("Roles"),
        choices=ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        initial=["member"],
    )

    def handle(self, request, data):
        project_id = self.initial["project_id"]
        try:
            member = facade.add_member(request, project_id, data["username"], data["roles"])
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to add member."))
            return False
        messages.success(
            request,
            _('Added "%(username)s" to this project as %(roles)s.')
            % {"username": member["username"], "roles": ", ".join(member["roles"])},
        )
        return member


class ChangeMemberRoleForm(AddMemberForm):
    # Read-only: the target member is fixed by the row action that opened
    # this form, not user-editable. Since the field is `disabled`, Django
    # ignores any submitted value and uses the initial value instead, so
    # this can't be tampered with via the POST body.
    username = forms.CharField(label=_("Username"), disabled=True)

    def handle(self, request, data):
        project_id = self.initial["project_id"]
        try:
            # add_member has idempotent "set roles" semantics -- posting
            # an existing member's username with a new role set changes
            # it rather than duplicating grants. See project-facade/app.py.
            member = facade.add_member(request, project_id, data["username"], data["roles"])
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to change member roles."))
            return False
        messages.success(
            request,
            _('Changed "%(username)s"\'s roles to %(roles)s.')
            % {"username": member["username"], "roles": ", ".join(member["roles"])},
        )
        return member


class LeaveProjectForm(horizon_forms.SelfHandlingForm):
    def handle(self, request, data):
        project_id = self.initial["project_id"]
        try:
            facade.leave_project(request, project_id)
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to leave this project."))
            return False
        messages.success(request, _("You have left this project."))
        return True
