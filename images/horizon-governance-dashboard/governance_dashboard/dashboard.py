from django.utils.translation import gettext_lazy as _
import horizon


class Governance(horizon.Dashboard):
    name = _("Governance")
    slug = "governance"
    panels = ("governance_overview",)
    default_panel = "governance_overview"


horizon.register(Governance)
