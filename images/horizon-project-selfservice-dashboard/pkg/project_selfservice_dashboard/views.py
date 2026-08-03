from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from horizon import forms as horizon_forms

from . import forms


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
