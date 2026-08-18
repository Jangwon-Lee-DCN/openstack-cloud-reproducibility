from django.conf import settings

from governance_dashboard.client import GovernanceClient


def client_for(request):
    identity = {
        "X-Auth-Token": request.user.token.id,
        "X-Domain-Id": request.user.domain_id,
        "X-Project-Id": request.user.project_id,
        "X-User-Id": request.user.id,
        "X-Roles": ",".join(role["name"] for role in request.user.roles),
    }
    return GovernanceClient(
        settings.GOVERNANCE_FAKE_API_ENDPOINT,
        identity,
        ca_file=getattr(settings, "GOVERNANCE_API_CA_FILE", None),
    )


def is_cost_admin(request):
    return any(role["name"] in {"admin", "system_reader"}
               for role in request.user.roles)
