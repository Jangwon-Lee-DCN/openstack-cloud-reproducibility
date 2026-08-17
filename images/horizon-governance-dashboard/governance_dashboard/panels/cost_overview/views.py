from django.views.generic import TemplateView

from governance_dashboard.client import COST_COLLECTIONS
from governance_dashboard.cost import client_for


class IndexView(TemplateView):
    template_name = "cost_management/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = client_for(self.request)
        context["sections"] = [(label, client.list(collection)["items"])
                               for collection, label in COST_COLLECTIONS]
        return context
