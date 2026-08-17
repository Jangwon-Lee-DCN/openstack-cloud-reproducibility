from django.conf import settings

from governance_dashboard.client import GovernanceClient


def client_for(request):
    identity = {
        "X-Domain-Id": request.user.domain_id,
        "X-Project-Id": request.user.project_id,
        "X-User-Id": request.user.id,
        "X-Roles": ",".join(role["name"] for role in request.user.roles),
    }
    return GovernanceClient(settings.GOVERNANCE_FAKE_API_ENDPOINT, identity)


def is_cost_admin(request):
    return any(role["name"] in {"admin", "system_reader"}
               for role in request.user.roles)
