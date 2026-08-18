import os
import json
import urllib.request
import urllib.error

import pymysql

pymysql.install_as_MySQLdb()
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openstack_dashboard.settings")

import django

django.setup()
import openstack_dashboard.urls  # noqa: E402,F401
from django.conf import settings  # noqa: E402
from django.contrib.auth import middleware as auth_middleware  # noqa: E402
from django.test import Client, RequestFactory  # noqa: E402
from django.urls import reverse  # noqa: E402
from horizon import Horizon  # noqa: E402
from openstack_auth import utils as auth_utils  # noqa: E402
from governance_dashboard.client import COLLECTIONS  # noqa: E402
from governance_dashboard.cost import client_for, is_cost_admin  # noqa: E402

settings.TEMPLATES[0]["DIRS"].insert(0, "/tests")


class User:
    pass


payload = json.dumps({"auth": {"identity": {"methods": ["application_credential"],
    "application_credential": {"id": os.environ["APP_CRED_ID"],
                               "secret": os.environ["APP_CRED_SECRET"]}}}}).encode()
auth_url = os.environ["AUTH_URL"].rstrip("/")
if not auth_url.endswith("/v3"):
    auth_url += "/v3"
token_request = urllib.request.Request(
    auth_url + "/auth/tokens", data=payload,
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(token_request, timeout=10) as response:
    token_id = response.headers["X-Subject-Token"]
    token = json.load(response)["token"]
User.token = type("Token", (), {"id": token_id, "project": token["project"]})()
User.domain_id = token["user"]["domain"]["id"]
User.project_id = token["project"]["id"]
User.id = token["user"]["id"]
User.roles = token["roles"]
User.username = token["user"]["name"]
User.is_authenticated = True
User.is_superuser = False
User.authorized_tenants = []
User.user_domain_name = token["user"]["domain"].get("name", User.domain_id)
User.user_domain_id = User.domain_id
User.project_name = token["project"]["name"]
User.services_region = "seoul-ssu-1"
User.available_services_regions = ["seoul-ssu-1"]
User.system_scoped = False
User.is_system_user = False


factory = RequestFactory()


def scoped_request():
    scoped = factory.get("/")
    scoped.user = User()
    scoped._cached_user = scoped.user
    scoped.session = {}
    scoped.horizon = {}
    return scoped


request = scoped_request()
# A normal browser request reconstructs this Keystone user through Horizon's
# session backend.  This isolated Job has no Horizon session database, so bind
# the policy helper to the already verified, real Keystone token principal.
auth_utils.get_user = lambda scoped: scoped.user
auth_middleware.get_user = lambda scoped: User()
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
browser = Client(raise_request_exception=False)
for panel, expected in (("cost_overview", b"Cost Management"),
                        ("cost_budgets", b"Budgets"),
                        ("aws_cost_forecast", b"AWS Cost Forecast")):
    url = reverse(f"horizon:governance:{panel}:index")
    print(f"GET {url}", flush=True)
    response = browser.get(url)
    assert response.status_code == 200
    assert b'id="cost-management-content"' in response.content
    assert expected in response.content

# The development application credential deliberately has member/reader roles.
# Price & Calibration must therefore remain inaccessible through Horizon, while
# its backing collections are still exercised with the real scoped token.
request = scoped_request()
assert not is_cost_admin(request)
profiles_response = browser.get(reverse("horizon:governance:cost_profiles:index"))
assert profiles_response.status_code == 403
client = client_for(request)
for collection in ("aws-price-profiles", "aws-calibration-profiles"):
    assert "items" in client.list(collection)

print("PASS authenticated HTTP views, admin denial, and real Governance API collections")
