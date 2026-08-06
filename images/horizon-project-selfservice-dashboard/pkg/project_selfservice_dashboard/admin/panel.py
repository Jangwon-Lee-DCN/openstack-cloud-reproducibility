from django.utils.translation import gettext_lazy as _
import horizon


class ProjectOperations(horizon.Panel):
    name = _("Project Operations")
    slug = "project_operations"
