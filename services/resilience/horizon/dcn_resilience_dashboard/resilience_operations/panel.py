from django.utils.translation import gettext_lazy as _
import horizon

from dcn_resilience_dashboard import dashboard


class ResilienceOperations(horizon.Panel):
    name = _("Operations")
    slug = "resilience_operations"


dashboard.Resilience.register(ResilienceOperations)
