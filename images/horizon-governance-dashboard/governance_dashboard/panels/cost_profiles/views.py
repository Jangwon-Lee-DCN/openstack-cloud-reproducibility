from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView

from governance_dashboard.client import ADMIN_COST_COLLECTIONS
from governance_dashboard.cost import client_for, is_cost_admin


class IndexView(TemplateView):
    template_name = "cost_management/profiles.html"

    def get_context_data(self, **kwargs):
        if not is_cost_admin(self.request):
            raise PermissionDenied
        context = super().get_context_data(**kwargs)
        client = client_for(self.request)
        context["sections"] = [(label, client.list(collection)["items"])
                               for collection, label in ADMIN_COST_COLLECTIONS]
        return context
