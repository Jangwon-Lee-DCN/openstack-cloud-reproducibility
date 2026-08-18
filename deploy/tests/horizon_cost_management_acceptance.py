import os

import pymysql

pymysql.install_as_MySQLdb()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openstack_dashboard.settings")

import django

django.setup()
import openstack_dashboard.urls  # noqa: E402,F401
from django.test import RequestFactory  # noqa: E402
from django.urls import reverse  # noqa: E402
from horizon import Horizon  # noqa: E402
from governance_dashboard.client import COLLECTIONS  # noqa: E402
from governance_dashboard.panels.aws_forecast.views import IndexView as ForecastView  # noqa: E402
from governance_dashboard.panels.cost_budgets.views import IndexView as BudgetsView  # noqa: E402
from governance_dashboard.panels.cost_overview.views import IndexView as OverviewView  # noqa: E402
from governance_dashboard.panels.cost_profiles.views import IndexView as ProfilesView  # noqa: E402


class User:
    domain_id = "default"
    project_id = "00000000-0000-4000-8000-000000000001"
    id = "00000000-0000-4000-8000-000000000002"
    roles = [{"name": "admin"}, {"name": "member"}]


factory = RequestFactory()
request = factory.get("/")
request.user = User()
project = Horizon.get_dashboard("project")
governance = Horizon.get_dashboard("governance")
assert "cost_management" not in list(project.get_panel_groups())
group = governance.get_panel_group("cost_management")
assert group.panels == ["cost_overview", "cost_budgets", "aws_cost_forecast", "cost_profiles"]
assert not {"aws-price-profiles", "aws-calibration-profiles"} & {name for name, _ in COLLECTIONS}
for panel in group.panels:
    assert reverse(f"horizon:governance:{panel}:index").endswith(
        f"/governance/{panel}/"
    )
for view in (OverviewView, BudgetsView, ForecastView, ProfilesView):
    instance = view()
    instance.request = request
    context = instance.get_context_data()
    assert context is not None
print("PASS authenticated-equivalent hierarchy and real Governance API views")
