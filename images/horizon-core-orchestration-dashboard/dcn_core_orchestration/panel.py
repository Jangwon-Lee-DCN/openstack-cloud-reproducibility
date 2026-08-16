from django.utils.translation import gettext_lazy as _
import horizon


class CoreOrchestration(horizon.Panel):
    name = _("Templates & Auto Scaling")
    slug = "core_orchestration"
