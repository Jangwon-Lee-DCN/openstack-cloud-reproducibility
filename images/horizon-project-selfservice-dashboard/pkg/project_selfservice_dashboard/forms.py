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
    owner = forms.CharField(label=_("Owner"), help_text=_("Team or accountable person."))
    environment = forms.ChoiceField(
        label=_("Environment"),
        choices=(("production", _("Production")), ("staging", _("Staging")), ("development", _("Development")), ("test", _("Test"))),
    )
    cost_center = forms.CharField(label=_("Cost Center"), required=False)
    purpose = forms.CharField(label=_("Purpose"), required=False)
    initial_members = forms.CharField(
        label=_("Initial Members"), required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Optional usernames, one per line or comma-separated. They receive Member access."),
    )

    def handle(self, request, data):
        try:
            members = BulkAddMemberForm._parse_usernames(data.get("initial_members", ""))
            project = facade.create_project(
                request, data["name"], data.get("description", ""),
                tags=[
                    f"owner={data['owner']}", f"environment={data['environment']}",
                    *([f"cost_center={data['cost_center']}"] if data.get("cost_center") else []),
                    *([f"purpose={data['purpose']}"] if data.get("purpose") else []),
                ],
                initial_members=members,
            )
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


class DecommissionProjectForm(horizon_forms.SelfHandlingForm):
    project_id = forms.CharField(widget=forms.HiddenInput)
    project_name = forms.CharField(widget=forms.HiddenInput)
    action = forms.ChoiceField(
        label=_("Action"), widget=forms.RadioSelect,
        choices=(("disable", _("Disable for review")), ("delete", _("Permanently delete"))),
        initial="disable",
    )
    confirmation = forms.CharField(
        label=_("Type the project name to confirm"),
    )

    def clean_confirmation(self):
        value = self.cleaned_data["confirmation"]
        if value != self.initial["project_name"]:
            raise forms.ValidationError(_("Project name does not match."))
        return value

    def handle(self, request, data):
        try:
            if data["action"] == "disable":
                facade.update_project(request, data["project_id"], enabled=False)
            else:
                facade.delete_project(request, data["project_id"])
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        messages.success(request, _("Project lifecycle action completed."))
        return True


# Matches project-facade/app.py's ALLOWED_MEMBER_ROLES. The first three
# are the base access tiers; the rest are the platform's additive marker
# roles (reconcile-iam-dcn.sh) -- a member typically wants a base tier
# plus zero or more of these together (e.g. Member + Network Operator),
# since the marker roles alone don't grant ordinary project CRUD in
# vpc-facade's own authorization classes. This form doesn't enforce that
# combination; it just lets the project admin pick any set.
BASE_ROLE_CHOICES = [
    ("admin", _("Admin")),
    ("member", _("Member")),
    ("reader", _("Read Only")),
]
CAPABILITY_ROLE_CHOICES = [
    ("network-operator", _("Network Operator")),
    ("security-operator", _("Security Operator")),
    ("load-balancer_admin", _("Load Balancer Operator")),
    ("monitoring", _("Monitoring")),
]
# Role-bundle administration still needs the complete primitive role catalog.
ROLE_CHOICES = BASE_ROLE_CHOICES + CAPABILITY_ROLE_CHOICES


def _bundle_choices(request):
    """Shared by every form below that offers a role-bundle shortcut --
    fetched fresh per form render since bundles are admin-editable and a
    stale cached list would just offer options that no longer exist."""
    try:
        bundles = facade.list_role_bundles(request)
    except Exception:
        bundles = {}
    return [("", _("-- none, pick roles individually below --"))] + [
        (name, f"{name} ({', '.join(sorted(b['roles']))})") for name, b in sorted(bundles.items())
    ]


class AddMemberForm(horizon_forms.SelfHandlingForm):
    username = forms.ChoiceField(
        label=_("User"),
        choices=[("", _("Select a user"))],
        help_text=_("Only enabled users who are not already project members are selectable."),
    )
    bundle = forms.ChoiceField(
        label=_("Role Bundle"),
        required=False,
        choices=[("", "")],
        help_text=_("A named preset combining several roles at once -- see Role Bundles to define one. "
                     "Combines with any individually-checked roles below."),
    )
    base_role = forms.ChoiceField(
        label=_("Base Access"),
        choices=BASE_ROLE_CHOICES,
        widget=forms.RadioSelect,
        initial="member",
        help_text=_("Choose exactly one baseline permission tier."),
    )
    capabilities = forms.MultipleChoiceField(
        label=_("Additional Capabilities"),
        choices=CAPABILITY_ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text=_("Optional service-specific operator permissions added to the base access."),
    )

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["bundle"].choices = _bundle_choices(request)
        project_id = self.initial.get("project_id")
        if project_id and not self.fields["username"].disabled:
            try:
                candidates = facade.member_candidates(request, project_id)
                self.fields["username"].choices = [("", _("Select a user"))] + [
                    (
                        user["username"],
                        "%s%s" % (
                            user["username"],
                            " <%s>" % user["email"] if user.get("email") else "",
                        ),
                    )
                    for user in candidates
                    if user.get("enabled") and not user.get("is_member")
                ]
            except facade.FacadeError:
                self.fields["username"].choices = [("", _("User directory unavailable"))]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("base_role"):
            raise forms.ValidationError(_("Choose one base access tier."))
        return cleaned

    @staticmethod
    def _combined_roles(data):
        roles = [data["base_role"]] + list(data.get("capabilities") or [])
        if data.get("bundle"):
            roles.append(data["bundle"])
        return roles

    def handle(self, request, data):
        project_id = self.initial["project_id"]
        try:
            member = facade.add_member(request, project_id, data["username"], self._combined_roles(data))
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
            member = facade.add_member(request, project_id, data["username"], self._combined_roles(data))
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


class BulkAddMemberForm(horizon_forms.SelfHandlingForm):
    usernames = forms.CharField(
        label=_("Usernames"),
        help_text=_("One per line, or comma-separated."),
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    bundle = forms.ChoiceField(
        label=_("Role Bundle"),
        required=False,
        choices=[("", "")],
        help_text=_("Combines with any individually-checked roles below. Applied to every username above."),
    )
    base_role = forms.ChoiceField(
        label=_("Base Access"),
        choices=BASE_ROLE_CHOICES,
        widget=forms.RadioSelect,
        initial="member",
    )
    capabilities = forms.MultipleChoiceField(
        label=_("Additional Capabilities"),
        help_text=_("Applied to every username above."),
        choices=CAPABILITY_ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["bundle"].choices = _bundle_choices(request)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("base_role"):
            raise forms.ValidationError(_("Choose one base access tier."))
        return cleaned

    @staticmethod
    def _parse_usernames(raw):
        # Comma AND newline both accepted, since pasting from a
        # spreadsheet column and pasting a comma-separated list are both
        # realistic sources for this field.
        parts = raw.replace(",", "\n").splitlines()
        seen = set()
        usernames = []
        for part in parts:
            name = part.strip()
            if name and name not in seen:
                seen.add(name)
                usernames.append(name)
        return usernames

    def clean_usernames(self):
        usernames = self._parse_usernames(self.cleaned_data["usernames"])
        if not usernames:
            raise forms.ValidationError(_("Enter at least one username."))
        try:
            candidates = facade.member_candidates(
                self.request, self.initial["project_id"]
            )
        except facade.FacadeError as exc:
            raise forms.ValidationError(str(exc)) from exc
        by_name = {candidate["username"]: candidate for candidate in candidates}
        unknown = [name for name in usernames if name not in by_name]
        disabled = [name for name in usernames if name in by_name and not by_name[name]["enabled"]]
        existing = [name for name in usernames if name in by_name and by_name[name]["is_member"]]
        errors = []
        if unknown:
            errors.append(_("Not found in this domain: %s") % ", ".join(unknown))
        if disabled:
            errors.append(_("Disabled users: %s") % ", ".join(disabled))
        if existing:
            errors.append(_("Already members: %s") % ", ".join(existing))
        if errors:
            raise forms.ValidationError(errors)
        return usernames

    def handle(self, request, data):
        project_id = self.initial["project_id"]
        roles = [data["base_role"]] + list(data.get("capabilities") or [])
        if data.get("bundle"):
            roles.append(data["bundle"])
        added, failed = [], []
        for username in data["usernames"]:
            try:
                member = facade.add_member(request, project_id, username, roles)
                added.append(member["username"])
            except facade.FacadeError as exc:
                failed.append((username, str(exc)))
            except Exception:
                failed.append((username, str(_("unexpected error"))))
        if added:
            messages.success(
                request,
                _('Added %(count)d member(s) as %(roles)s: %(names)s.')
                % {"count": len(added), "roles": ", ".join(roles), "names": ", ".join(added)},
            )
        for username, error in failed:
            messages.error(request, _('Could not add "%(username)s": %(error)s') % {"username": username, "error": error})
        # A partial failure (e.g. one bad username in a batch of ten)
        # still closes the modal and refreshes the member list -- the per-
        # user error messages above already say exactly what didn't land,
        # and the successful adds shouldn't be hidden behind them.
        return added or not failed


class ProjectGroupForm(horizon_forms.SelfHandlingForm):
    group_id = forms.ChoiceField(label=_("Group"), choices=[])
    base_role = forms.ChoiceField(
        label=_("Base Access"), choices=BASE_ROLE_CHOICES, widget=forms.RadioSelect, initial="member"
    )
    capabilities = forms.MultipleChoiceField(
        label=_("Additional Capabilities"), choices=CAPABILITY_ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple, required=False,
    )

    def __init__(self, request, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        try:
            groups = facade.project_groups(request, self.initial["project_id"])
            editing = self.initial.get("group_id")
            self.fields["group_id"].choices = [
                (group["group_id"], group["name"])
                for group in groups["candidates"]
                if editing == group["group_id"] or not group["assigned"]
            ]
            if editing:
                self.fields["group_id"].disabled = True
        except facade.FacadeError:
            self.fields["group_id"].choices = []

    def handle(self, request, data):
        roles = [data["base_role"]] + list(data.get("capabilities") or [])
        try:
            return facade.set_project_group(
                request, self.initial["project_id"], data["group_id"], roles
            )
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False


class TransferOwnershipForm(horizon_forms.SelfHandlingForm):
    # Read-only, same reasoning as ChangeMemberRoleForm.username above --
    # the target is fixed by the row action that opened this form.
    username = forms.CharField(label=_("New Admin"), disabled=True)

    def handle(self, request, data):
        project_id = self.initial["project_id"]
        try:
            result = facade.transfer_ownership(request, project_id, data["username"])
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to transfer ownership."))
            return False
        messages.success(
            request,
            _('Transferred ownership of this project to "%s". You are now a regular member.')
            % result["new_admin"],
        )
        return result


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


class RoleBundleForm(horizon_forms.SelfHandlingForm):
    """Create or update a named bundle of the existing roles (e.g. "VPC
    Operator" = network-operator + security-operator) -- domain-admin
    only, enforced by project-facade's PUT /v1/role-bundles/<name>
    itself; a non-admin submitting this form sees that endpoint's own
    403 as a form error, same pattern as everywhere else in this app.
    """

    name = forms.CharField(
        label=_("Bundle Name"),
        help_text=_("Must not be the same as a real role name (admin, member, etc.)."),
    )
    description = forms.CharField(label=_("Description"), required=False)
    roles = forms.MultipleChoiceField(
        label=_("Roles"),
        choices=ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    required_tag = forms.CharField(
        label=_("Required Project Tag"),
        required=False,
        help_text=_(
            "If set, this bundle can only be granted on a project carrying this exact "
            "tag (see \"Manage Tags\" on Domain Projects Overview). Leave blank for no "
            "restriction."
        ),
    )

    def handle(self, request, data):
        try:
            bundle = facade.put_role_bundle(
                request, data["name"], data.get("description", ""), data["roles"], data.get("required_tag", "")
            )
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to save this role bundle."))
            return False
        messages.success(
            request,
            _('Saved role bundle "%(name)s": %(roles)s.')
            % {"name": bundle["name"], "roles": ", ".join(bundle["roles"])},
        )
        return bundle


class ManageProjectTagsForm(horizon_forms.SelfHandlingForm):
    """Keystone's own native project tags (see project-facade app.py's
    list_project_tags/set_project_tags) -- surfaced here mainly so a
    domain admin has somewhere to set the tag a role bundle's
    `required_tag` checks against."""

    project_id = forms.CharField(widget=forms.HiddenInput)
    owner = forms.CharField(label=_("Owner"), required=False)
    environment = forms.ChoiceField(
        label=_("Environment"), required=False,
        choices=(("", _("Not set")), ("production", _("Production")), ("staging", _("Staging")), ("development", _("Development")), ("test", _("Test"))),
    )
    cost_center = forms.CharField(label=_("Cost Center"), required=False)
    purpose = forms.CharField(label=_("Purpose"), required=False)
    extra_tags = forms.CharField(
        label=_("Additional Tags"),
        required=False,
        help_text=_("Comma-separated labels without '='."),
    )

    def handle(self, request, data):
        tags = [t.strip() for t in data.get("extra_tags", "").split(",") if t.strip()]
        for key in ("owner", "environment", "cost_center", "purpose"):
            if data.get(key):
                tags.append("%s=%s" % (key, data[key].strip()))
        try:
            saved = facade.set_project_tags(request, data["project_id"], tags)
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to save this project's tags."))
            return False
        messages.success(request, _("Saved tags: %s") % (", ".join(saved) or _("(none)")))
        return True


class CreateApplicationCredentialForm(horizon_forms.SelfHandlingForm):
    """Self-service, not admin-gated -- see project-facade app.py's
    module docstring for why Keystone's own application-credentials API
    is self-only regardless of role. The one thing this form adds beyond
    Keystone's own defaults: an expiration is mandatory, there is no
    "never expires" option."""

    name = forms.CharField(label=_("Name"), max_length=255)
    description = forms.CharField(label=_("Description"), required=False)
    expires_in_days = forms.IntegerField(
        label=_("Expires In (days)"),
        min_value=1,
        max_value=365,
        initial=90,
        help_text=_(
            "Application credentials must have an expiration -- there is no "
            "\"never expires\" option for self-service credentials."
        ),
    )

    def handle(self, request, data):
        try:
            cred = facade.create_application_credential(
                request, data["name"], data.get("description", ""), data["expires_in_days"]
            )
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to create application credential."))
            return False
        messages.success(
            request,
            _(
                'Created application credential "%(name)s". Its secret is shown only '
                "once -- copy it now, it cannot be retrieved again: %(secret)s"
            )
            % {"name": cred["name"], "secret": cred["secret"]},
        )
        return cred


class RequestQuotaIncreaseForm(horizon_forms.SelfHandlingForm):
    """Does not change any quota itself -- see project-facade app.py's
    request_quota_increase for why. Just durably logs the request so a
    domain admin sees it (in this project's own Audit Log) instead of
    it arriving as a message that gets lost."""

    project_id = forms.CharField(widget=forms.HiddenInput)
    resource = forms.CharField(
        label=_("Resource"),
        help_text=_('E.g. "vCPUs", "Volumes", "Storage (GiB)" -- see the Quota & Usage tab for exact names.'),
    )
    requested_amount = forms.CharField(label=_("Requested Amount"))
    justification = forms.CharField(
        label=_("Justification"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def handle(self, request, data):
        try:
            facade.request_quota_increase(
                request,
                data["project_id"],
                data["resource"],
                data["requested_amount"],
                data.get("justification", ""),
            )
        except facade.FacadeError as exc:
            self.api_error(str(exc))
            return False
        except Exception:
            exceptions.handle(request, _("Unable to submit this quota request."))
            return False
        messages.success(
            request,
            _('Requested %(amount)s for "%(resource)s". Visible to this project\'s domain admin in its Audit Log.')
            % {"amount": data["requested_amount"], "resource": data["resource"]},
        )
        return True
