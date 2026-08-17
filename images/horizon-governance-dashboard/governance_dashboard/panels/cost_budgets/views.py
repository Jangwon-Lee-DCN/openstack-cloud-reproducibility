from django.views.generic import TemplateView

from governance_dashboard.cost import client_for


class IndexView(TemplateView):
    template_name = "cost_management/budgets.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["budgets"] = client_for(self.request).list("budgets")["items"]
        return context
