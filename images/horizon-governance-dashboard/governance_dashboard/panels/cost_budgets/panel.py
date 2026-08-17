from django.utils.translation import gettext_lazy as _
import horizon


class CostBudgets(horizon.Panel):
    name = _("Budgets")
    slug = "cost_budgets"
