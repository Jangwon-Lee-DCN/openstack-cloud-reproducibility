from django.views.generic import TemplateView

from governance_dashboard.cost import client_for


class IndexView(TemplateView):
    template_name = "cost_management/aws_forecast.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = client_for(self.request)
        context["price_profiles"] = client.list("aws-price-profiles")["items"]
        context["calibration_profiles"] = client.list("aws-calibration-profiles")["items"]
        context["budgets"] = client.list("budgets")["items"]
        query = self.request.GET
        if query.get("period") and query.get("price_profile_id"):
            context["forecast"] = client.aws_forecast(
                period=query["period"], price_profile_id=query["price_profile_id"],
                calibration_profile_id=query.get("calibration_profile_id") or None,
                budget_id=query.get("budget_id") or None,
                elapsed_fraction=query.get("elapsed_fraction") or None)
        return context
