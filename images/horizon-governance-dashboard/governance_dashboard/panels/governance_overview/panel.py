from django.utils.translation import gettext_lazy as _
import horizon

from governance_dashboard import dashboard


class GovernanceOverview(horizon.Panel):
    name = _("Overview")
    slug = "governance_overview"


dashboard.Governance.register(GovernanceOverview)
