from django.conf import settings
from django.utils.translation import gettext_lazy as _

import horizon

from openstack_dashboard.dashboards.admin import dashboard


class Ironic(horizon.Panel):
    name = _("Ironic Bare Metal Provisioning")
    slug = "ironic"
    permissions = ("openstack.services.baremetal",)

    def allowed(self, context):
        if not super().allowed(context):
            return False
        request = context.get("request")
        user = getattr(request, "user", None)
        expected_project = getattr(settings, "DCN_BAREMETAL_ADMIN_PROJECT_ID", "")
        if not user or not expected_project or getattr(user, "project_id", None) != expected_project:
            return False
        roles = {
            role.get("name") if isinstance(role, dict) else getattr(role, "name", role)
            for role in (getattr(user, "roles", None) or [])
        }
        return "baremetal_admin" in roles


dashboard.Admin.register(Ironic)
