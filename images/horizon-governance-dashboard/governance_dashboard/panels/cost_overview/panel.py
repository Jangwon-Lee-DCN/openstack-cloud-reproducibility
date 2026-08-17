from django.utils.translation import gettext_lazy as _
import horizon


class CostOverview(horizon.Panel):
    name = _("Overview")
    slug = "cost_overview"
