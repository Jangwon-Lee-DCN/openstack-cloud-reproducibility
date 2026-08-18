from django.utils.translation import gettext_lazy as _
import horizon


class AwsCostForecast(horizon.Panel):
    name = _("AWS Cost Forecast")
    slug = "aws_cost_forecast"
