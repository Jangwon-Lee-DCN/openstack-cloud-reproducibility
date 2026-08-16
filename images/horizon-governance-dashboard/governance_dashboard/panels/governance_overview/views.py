from django.conf import settings
from django.views.generic import TemplateView

from governance_dashboard.client import COLLECTIONS, GovernanceClient


class IndexView(TemplateView):
    template_name = "governance/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request
        identity = {
            "X-Domain-Id": request.user.domain_id,
            "X-Project-Id": request.user.project_id,
            "X-User-Id": request.user.id,
            "X-Roles": ",".join(role["name"] for role in request.user.roles),
        }
        client = GovernanceClient(settings.GOVERNANCE_FAKE_API_ENDPOINT, identity)
        context["sections"] = [(label, client.list(collection)["items"])
                               for collection, label in COLLECTIONS]
        return context
