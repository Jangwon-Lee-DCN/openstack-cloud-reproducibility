from django.utils.translation import gettext_lazy as _
import horizon


class CostProfiles(horizon.Panel):
    name = _("Price & Calibration")
    slug = "cost_profiles"

    def allowed(self, context):
        return any(role["name"] in {"admin", "system_reader"}
                   for role in context["request"].user.roles)
