from django.utils.translation import gettext_lazy as _
import horizon


class Resilience(horizon.Dashboard):
    name = _("Resilience")
    slug = "resilience"
    panels = ("resilience_operations",)
    default_panel = "resilience_operations"


horizon.register(Resilience)
