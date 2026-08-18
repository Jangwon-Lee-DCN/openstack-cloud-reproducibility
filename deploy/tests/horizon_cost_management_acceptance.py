import os
import json
import urllib.request

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
    pass


payload = json.dumps({"auth": {"identity": {"methods": ["application_credential"],
    "application_credential": {"id": os.environ["APP_CRED_ID"],
                               "secret": os.environ["APP_CRED_SECRET"]}}}}).encode()
token_request = urllib.request.Request(
    os.environ["AUTH_URL"].rstrip("/") + "/auth/tokens", data=payload,
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(token_request, timeout=10) as response:
    token_id = response.headers["X-Subject-Token"]
    token = json.load(response)["token"]
User.token = type("Token", (), {"id": token_id})()
User.domain_id = token["user"]["domain"]["id"]
User.project_id = token["project"]["id"]
User.id = token["user"]["id"]
User.roles = token["roles"]


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
