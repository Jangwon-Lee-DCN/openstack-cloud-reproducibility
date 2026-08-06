"""project-facade: self-service Keystone project lifecycle API.

Lets a user holding the domain-scoped `project-creator` marker role create
their own project under that domain, automatically becoming full `admin`
on the project they just created. Update/delete of any project requires
the caller to already be project-scoped `admin` on that specific project,
and refuses outright if the project has Keystone's `options.immutable`
flag set (used to protect a domain's designated admin project, e.g. `dcn`
in the `dcn` domain -- see docs/proposals/iam-hardening/README.md, "New
permission tier: self-service project lifecycle").

Also lets a project's admin manage who else has access to it (add, remove,
or change a member's role set: admin/member/reader plus zero or more of
the platform's additive marker roles -- network-operator/security-
operator/load-balancer_admin/monitoring) -- the natural next step once a
project can be self-service-created at all: someone who owns a project
needs to be able to invite teammates into it, and hand them a narrower
capability like "manage VPC peering for this project" specifically,
without asking a platform admin every time. Unlike update/delete, member
management (1) accepts a *domain-scoped* admin of the project's own
domain, not only a project-scoped admin on that exact project -- a
genuine domain admin's `admin` role is granted at domain scope only (see
reconcile-iam-dcn.sh), so restricting this to project-scoped admin would
lock every real domain admin out of managing their own domain's shared
project -- and (2) is not blocked by the project's `options.immutable`
flag, since that flag protects a project's own structure (rename/delete),
not who has access to it, and the domain's shared/admin project (e.g.
`dcn`) still needs its membership manageable day to day. Refuses to
demote or remove a project's last remaining admin, so a project can never
be locked out of its own self-service management. Any member can also
remove *themselves* (`POST .../leave`) without needing admin rights at
all -- leaving is not an admin action -- subject to the same last-admin
protection.

`GET .../audit-log` exposes a read-only trail of who did what to a
project (including denied attempts), read back out of this service's own
request logs via Loki -- see `_query_loki_project_lines` -- rather than a
separate datastore. Same admin-or-domain-admin authorization as member
management.

`POST .../transfer-ownership` atomically grants a named user admin and
demotes the caller to member, replacing the two-step (change their role,
then separately leave/demote yourself) manual process -- see
`transfer_ownership` for why this is the one path that never hits the
last-admin guard.

`GET /v1/my-access` answers "which projects can I actually get into, and
with what role" for the caller themselves, across the whole domain --
group-derived roles included, the thing a stock session token can't
answer without walking every project one at a time. `GET
/v1/domain-projects-overview` is the domain-admin equivalent: every
project in the domain with its admin(s), member count, and last
self-service activity, gated the same way `check_domain_admin` is.

`GET .../simulate-access` is a per-action dry run of the caller's own
current access to a project (see `simulate_access`) -- not a
hypothetical "what if I had role X" policy evaluator. `/v1/role-bundles`
(GET/PUT/DELETE) let a domain admin define named bundles of the existing
roles (e.g. "VPC Operator" = network-operator + security-operator),
grantable as a single name via `add_member`/`bulk invite` instead of
selecting each role individually -- see `_expand_role_bundles`, stored
in a ConfigMap since this service runs multiple replicas.
`GET /v1/role-bundles/audit-log` is that domain-scoped resource's own
audit trail (role bundles aren't tied to any one project, so this can't
live in a project's own `.../audit-log` the way everything else does).
`.../audit-log` itself now also merges in vpc-facade's own richer audit
history for the same project (`_vpc_facade_audit_entries`) and a
mutating/failed-request slice of Cinder/Nova/Neutron's own oslo.log
output (`_openstack_service_audit_entries` -- coverage varies a lot by
service, see that function's docstring for exactly what's real and
what's a known gap).

DELETE also refuses to remove a project that still has active Nova/
Cinder/Neutron resources (instances, volumes, networks, routers, floating
IPs) -- Keystone's own project delete has no idea these exist and would
silently orphan them. Checking this requires a *project-scoped* token for
the target project (Nova's policy for listing servers hard-requires
`scope_types: ['project']`; a domain-scoped token, even with the `admin`
role, fails that scope check regardless of role -- confirmed live), which
this service's own domain-scoped credential cannot obtain on its own. So
immediately before the check, project-facade grants its own service user
a direct `admin` role on the target project (the same Keystone grant
mechanism it already uses for the project's human owner), uses that to
mint a project-scoped token for the resource check, and revokes its own
grant again immediately if the delete is blocked -- so the elevated access
exists for the span of one request, never as a standing grant. If the
delete proceeds, no revoke is needed: Keystone's project delete removes
every role assignment on it anyway.

This service holds its own Keystone service-account credential
(domain-scoped `admin` on exactly the domain it administers -- see
OS_DOMAIN_NAME below, not system-scope) and performs every Keystone write
itself after checking the caller's token and role assignments -- callers
never get elevated Keystone credentials themselves. This mirrors the same
"facade holds elevated credentials, itself enforces the persona/action
matrix" pattern already used by vpc-facade (see "Authority boundaries" in
the IAM hardening doc).
"""

import csv
import datetime
import io
import json
import logging
import os
import re
import time

import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("project-facade")

OS_AUTH_URL = os.environ["OS_AUTH_URL"]
OS_USERNAME = os.environ["OS_USERNAME"]
OS_PASSWORD = os.environ["OS_PASSWORD"]
OS_USER_DOMAIN_NAME = os.environ["OS_USER_DOMAIN_NAME"]
# The single domain this service instance is authorized to administer --
# it only ever holds a domain-scoped credential for this one domain.
# Requests naming a different domain are rejected outright rather than
# attempted, since the service credential has no rights there anyway.
OS_DOMAIN_NAME = os.environ.get("OS_DOMAIN_NAME", "dcn")

# Internal cluster Service DNS for the pre-delete resource check -- same
# in-cluster addressing convention as OS_AUTH_URL above, overridable for
# environments where these differ.
NOVA_URL = os.environ.get("NOVA_ENDPOINT", "http://nova-api.openstack.svc.cluster.local:8774/v2.1")
CINDER_URL = os.environ.get("CINDER_ENDPOINT", "http://cinder-api.openstack.svc.cluster.local:8776/v3")
NEUTRON_URL = os.environ.get("NEUTRON_ENDPOINT", "http://neutron-server.openstack.svc.cluster.local:9696/v2.0")
# This service's own request logs (already emitted for every mutating
# action, see the log.info/log.warning calls below) are the audit trail --
# no separate datastore. Alloy ships stdout from every pod cluster-wide
# into Loki already; this just reads it back out, scoped to this
# service's own log stream.
LOKI_URL = os.environ.get("LOKI_ENDPOINT", "http://loki.monitoring.svc.cluster.local:3100")
LOKI_JOB_LABEL = os.environ.get("LOKI_JOB_LABEL", "openstack/project-facade")
AUDIT_LOG_LOOKBACK_SECONDS = int(os.environ.get("AUDIT_LOG_LOOKBACK_SECONDS", str(30 * 24 * 3600)))
# vpc-facade's own /v1/audit is richer than anything this service could
# derive from its own logs (Kubernetes Events plus SecurityGroup/
# ElasticIP/NetworkInterface status history, not just request logs) --
# see project_audit_log below for how its entries get merged in rather
# than duplicated.
VPC_FACADE_URL = os.environ.get("VPC_FACADE_ENDPOINT", "http://vpc-facade.vpc-control-plane-system.svc.cluster.local:8090")

# In-cluster Kubernetes API access for role bundles below -- plain REST
# calls via `requests` (the same HTTP client this whole file already
# uses for everything else) rather than pulling in the full kubernetes
# client library for what's really just one GET and one PATCH.
K8S_API_URL = "https://kubernetes.default.svc"
K8S_SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"
ROLE_BUNDLES_NAMESPACE = os.environ.get("ROLE_BUNDLES_NAMESPACE", "openstack")
ROLE_BUNDLES_CONFIGMAP = os.environ.get("ROLE_BUNDLES_CONFIGMAP", "project-facade-role-bundles")

PROJECT_CREATOR_ROLE = "project-creator"
ADMIN_ROLE = "admin"
# admin/member/reader are the base access tiers (mutually exclusive in
# practice, though not enforced as such here -- see add_member). The rest
# are the same additive marker roles reconcile-iam-dcn.sh's platform-wide
# personas already grant via Keycloak groups (network-operator,
# security-operator, load-balancer_admin, monitoring); exposing them here
# lets a project owner grant a teammate a narrower capability (e.g. "can
# manage VPC peering for this project") without asking a platform admin
# to add them to a domain-wide persona group.
ALLOWED_MEMBER_ROLES = {
    "admin",
    "member",
    "reader",
    "network-operator",
    "security-operator",
    "load-balancer_admin",
    "monitoring",
}

_service_token_cache = {"token": None, "expires_at": 0.0}
_role_id_cache = {}
_own_user_id_cache = {"id": None}


def _parse_expires_at(expires_at_str):
    fmt = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in expires_at_str else "%Y-%m-%dT%H:%M:%S%z"
    return datetime.datetime.strptime(expires_at_str, fmt).timestamp()


def get_service_token():
    now = time.time()
    if _service_token_cache["token"] and _service_token_cache["expires_at"] - now > 60:
        return _service_token_cache["token"]
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": OS_USERNAME,
                        "domain": {"name": OS_USER_DOMAIN_NAME},
                        "password": OS_PASSWORD,
                    }
                },
            },
            "scope": {"domain": {"name": OS_DOMAIN_NAME}},
        }
    }
    r = requests.post(f"{OS_AUTH_URL}/auth/tokens", json=body, timeout=10)
    r.raise_for_status()
    token = r.headers["X-Subject-Token"]
    expires_at = _parse_expires_at(r.json()["token"]["expires_at"])
    _service_token_cache.update(token=token, expires_at=expires_at)
    return token


def keystone_headers():
    return {"X-Auth-Token": get_service_token(), "Content-Type": "application/json"}


def validate_caller_token(caller_token):
    r = requests.get(
        f"{OS_AUTH_URL}/auth/tokens",
        headers={"X-Auth-Token": get_service_token(), "X-Subject-Token": caller_token},
        timeout=10,
    )
    if r.status_code != 200:
        return None
    data = r.json()["token"]
    return data["user"]["id"], data["user"]["name"]


def get_domain_id(domain_name):
    r = requests.get(
        f"{OS_AUTH_URL}/domains", headers=keystone_headers(), params={"name": domain_name}, timeout=10
    )
    r.raise_for_status()
    domains = r.json()["domains"]
    return domains[0]["id"] if domains else None


def role_id_by_name(role_name):
    if role_name in _role_id_cache:
        return _role_id_cache[role_name]
    r = requests.get(f"{OS_AUTH_URL}/roles", headers=keystone_headers(), params={"name": role_name}, timeout=10)
    r.raise_for_status()
    roles = r.json()["roles"]
    role_id = roles[0]["id"] if roles else None
    if role_id:
        _role_id_cache[role_name] = role_id
    return role_id


def _own_user_id():
    if _own_user_id_cache["id"]:
        return _own_user_id_cache["id"]
    token = get_service_token()
    r = requests.get(
        f"{OS_AUTH_URL}/auth/tokens",
        headers={"X-Auth-Token": token, "X-Subject-Token": token},
        timeout=10,
    )
    r.raise_for_status()
    user_id = r.json()["token"]["user"]["id"]
    _own_user_id_cache["id"] = user_id
    return user_id


def _get_project_scoped_token(project_id):
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": OS_USERNAME,
                        "domain": {"name": OS_USER_DOMAIN_NAME},
                        "password": OS_PASSWORD,
                    }
                },
            },
            "scope": {"project": {"id": project_id}},
        }
    }
    r = requests.post(f"{OS_AUTH_URL}/auth/tokens", json=body, timeout=10)
    r.raise_for_status()
    return r.headers["X-Subject-Token"]


def _active_resource_blockers(project_id):
    """Returns a list of human-readable strings describing anything on
    this project that a Keystone-only project delete would silently
    orphan (empty list means the project is safe to delete). Requires a
    project-scoped token -- see the module docstring for why."""
    headers = {"X-Auth-Token": _get_project_scoped_token(project_id)}
    blockers = []

    r = requests.get(f"{NOVA_URL}/servers/detail", headers=headers, timeout=10)
    r.raise_for_status()
    count = len(r.json()["servers"])
    if count:
        blockers.append(f"{count} instance(s)")

    r = requests.get(f"{CINDER_URL}/volumes/detail", headers=headers, timeout=10)
    r.raise_for_status()
    count = len(r.json()["volumes"])
    if count:
        blockers.append(f"{count} volume(s)")

    for resource, label in (
        ("networks", "network(s)"),
        ("routers", "router(s)"),
        ("floatingips", "floating IP(s)"),
    ):
        r = requests.get(
            f"{NEUTRON_URL}/{resource}", headers=headers, params={"project_id": project_id}, timeout=10
        )
        r.raise_for_status()
        count = len(r.json()[resource])
        if count:
            blockers.append(f"{count} {label}")

    return blockers


def _user_group_ids(user_id):
    # GET /v3/role_assignments?user.id=...&effective=true (used here until
    # 2026-08-03) never sees federated *expiring* group membership --
    # confirmed live, the hard way: keystone.assignment has zero references
    # to the expiring_user_group_membership table at all, while
    # keystone.identity.backends.sql.list_groups_for_user (the backend for
    # GET /v3/users/{id}/groups, used here instead) explicitly unions both
    # the permanent UserGroupMembership table and that expiring one. A real
    # Google-federated user showed a real DB row in
    # expiring_user_group_membership for openstack-project-creators, and
    # /users/{id}/groups correctly listed it, while /role_assignments kept
    # returning nothing for the same user at the same moment -- so
    # role_assignments is simply the wrong endpoint for "what groups is
    # this specific user actually in right now," regardless of TTL.
    r = requests.get(
        f"{OS_AUTH_URL}/users/{user_id}/groups", headers=keystone_headers(), timeout=10
    )
    r.raise_for_status()
    return {g["id"] for g in r.json()["groups"]}


def _group_ids_with_role_at_domain(domain_id, role_id):
    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"role.id": role_id, "scope.domain.id": domain_id},
        timeout=10,
    )
    r.raise_for_status()
    return {a["group"]["id"] for a in r.json()["role_assignments"] if "group" in a}


def _group_ids_with_role_at_project(project_id, role_id):
    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"role.id": role_id, "scope.project.id": project_id},
        timeout=10,
    )
    r.raise_for_status()
    return {a["group"]["id"] for a in r.json()["role_assignments"] if "group" in a}


def user_has_domain_role(user_id, domain_id, role_name):
    role_id = role_id_by_name(role_name)
    if not role_id:
        return False
    user_groups = _user_group_ids(user_id)
    if not user_groups:
        return False
    granted_groups = _group_ids_with_role_at_domain(domain_id, role_id)
    return bool(user_groups & granted_groups)


def user_has_system_admin_role(caller_token, user_id):
    """True if this user directly holds `admin` at system scope -- the
    real cloud-wide administrator (e.g. the bootstrap "admin" account,
    confirmed live to hold exactly this), who should pass every
    domain-admin check in this service for OS_DOMAIN_NAME same as any
    other domain, without needing a direct or group-derived grant on
    that specific domain.

    Deliberately queries with the CALLER's own token, not this
    service's domain-scoped service credential (keystone_headers()) --
    confirmed live that the two give different answers for the exact
    same query. This service's credential is intentionally scoped to
    administer only OS_DOMAIN_NAME (see the module docstring), and
    Keystone's role_assignments API enforces that boundary: querying
    another user's assignments with it silently returns nothing for
    anything outside that domain, including system-scope grants, even
    though the data exists. The caller's own token, whatever scope it's
    currently using, is allowed to see the caller's *own* full role
    assignment set via Keystone's self-lookup allowance -- confirmed by
    comparing both queries live for the same admin user.

    Also checked separately from user_has_domain_role because Keystone's
    role_assignments API on this deployment silently drops system-scoped
    entries when effective=true is passed (confirmed live) -- so this
    deliberately queries without it, at the cost of only seeing *direct*
    system-scope grants, not group-derived ones (there's no
    effective-expansion path here that doesn't also lose the
    system-scope entries)."""
    role_id = role_id_by_name(ADMIN_ROLE)
    if not role_id:
        return False
    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers={"X-Auth-Token": caller_token},
        params={"user.id": user_id},
        timeout=10,
    )
    if r.status_code != 200:
        return False
    return any(a["role"]["id"] == role_id and "system" in a.get("scope", {}) for a in r.json()["role_assignments"])


def user_has_project_role(user_id, project_id, role_name):
    role_id = role_id_by_name(role_name)
    if not role_id:
        return False
    # A direct user-level grant (e.g. the admin role project-facade itself
    # grants a project's creator) is still a plain, permanent, non-expiring
    # assignment -- role_assignments sees those correctly, so check them
    # too, not just group-derived ones.
    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"user.id": user_id, "scope.project.id": project_id, "effective": "true"},
        timeout=10,
    )
    r.raise_for_status()
    if any(a["role"]["id"] == role_id for a in r.json()["role_assignments"]):
        return True
    user_groups = _user_group_ids(user_id)
    if not user_groups:
        return False
    granted_groups = _group_ids_with_role_at_project(project_id, role_id)
    return bool(user_groups & granted_groups)


@app.route("/v1/projects", methods=["POST"])
def create_project():
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401

    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, user_name = ident

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    domain_name = body.get("domain") or OS_DOMAIN_NAME

    if not name:
        return jsonify(error="'name' is required"), 400
    if len(name) > 64:
        return jsonify(error="'name' must be at most 64 characters"), 400

    if domain_name != OS_DOMAIN_NAME:
        return jsonify(error=f"this service does not administer domain '{domain_name}'"), 403

    domain_id = get_domain_id(domain_name)
    if not domain_id:
        return jsonify(error=f"unknown domain '{domain_name}'"), 404

    if not user_has_domain_role(user_id, domain_id, PROJECT_CREATOR_ROLE):
        log.warning(
            "denied create_project: user=%s domain=%s missing role=%s", user_name, domain_name, PROJECT_CREATOR_ROLE
        )
        return jsonify(error="forbidden: missing project-creator role on this domain"), 403

    create_body = {
        "project": {
            "name": name,
            "domain_id": domain_id,
            "description": description
            or f"Self-service project created by {user_name} ({user_id}) via project-facade",
            "enabled": True,
        }
    }
    r = requests.post(f"{OS_AUTH_URL}/projects", headers=keystone_headers(), json=create_body, timeout=10)
    if r.status_code == 409:
        return jsonify(error=f"a project named '{name}' already exists in this domain"), 409
    r.raise_for_status()
    new_project = r.json()["project"]

    admin_role_id = role_id_by_name(ADMIN_ROLE)
    grant = requests.put(
        f"{OS_AUTH_URL}/projects/{new_project['id']}/users/{user_id}/roles/{admin_role_id}",
        headers=keystone_headers(),
        timeout=10,
    )
    grant.raise_for_status()

    log.info(
        "created project id=%s name=%s domain=%s owner=%s(%s)",
        new_project["id"],
        name,
        domain_name,
        user_name,
        user_id,
    )
    return jsonify(id=new_project["id"], name=new_project["name"], domain_id=domain_id), 201


def _load_target_project(project_id):
    r = requests.get(f"{OS_AUTH_URL}/projects/{project_id}", headers=keystone_headers(), timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()["project"]


def _authorize_project_admin(caller_token, project_id):
    """Shared guard for update/delete. Returns ((user_id, user_name), None) on
    success, or (None, (response, status)) on any failure."""
    ident = validate_caller_token(caller_token)
    if not ident:
        return None, (jsonify(error="invalid or expired token"), 401)
    user_id, user_name = ident

    project = _load_target_project(project_id)
    if not project:
        return None, (jsonify(error="project not found"), 404)

    if project.get("options", {}).get("immutable"):
        return None, (jsonify(error="this project is protected and cannot be modified or deleted"), 403)

    if not user_has_project_role(user_id, project_id, ADMIN_ROLE):
        log.warning("denied modify project=%s: user=%s missing project-scoped admin", project_id, user_name)
        return None, (jsonify(error="forbidden: you are not admin on this project"), 403)

    return (user_id, user_name), None


@app.route("/v1/projects/<project_id>", methods=["PATCH"])
def update_project(project_id):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401

    ident, err = _authorize_project_admin(caller_token, project_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}
    allowed = {k: v for k, v in body.items() if k in ("name", "description", "enabled")}
    if not allowed:
        return jsonify(error="no updatable fields provided (name, description, enabled)"), 400

    r = requests.patch(
        f"{OS_AUTH_URL}/projects/{project_id}",
        headers=keystone_headers(),
        json={"project": allowed},
        timeout=10,
    )
    r.raise_for_status()
    log.info("updated project=%s by=%s(%s) fields=%s", project_id, ident[1], ident[0], list(allowed))
    return jsonify(r.json()["project"]), 200


@app.route("/v1/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401

    ident, err = _authorize_project_admin(caller_token, project_id)
    if err:
        return err

    admin_role_id = role_id_by_name(ADMIN_ROLE)
    own_user_id = _own_user_id()

    grant = requests.put(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{own_user_id}/roles/{admin_role_id}",
        headers=keystone_headers(),
        timeout=10,
    )
    grant.raise_for_status()

    def _revoke_own_grant():
        rr = requests.delete(
            f"{OS_AUTH_URL}/projects/{project_id}/users/{own_user_id}/roles/{admin_role_id}",
            headers=keystone_headers(),
            timeout=10,
        )
        if rr.status_code not in (204, 404):
            rr.raise_for_status()

    try:
        blockers = _active_resource_blockers(project_id)
    except requests.RequestException:
        _revoke_own_grant()
        log.exception("resource check failed for project=%s", project_id)
        return jsonify(error="could not verify the project has no active resources; try again"), 502

    if blockers:
        _revoke_own_grant()
        log.warning("denied delete project=%s: still has %s", project_id, ", ".join(blockers))
        return (
            jsonify(error=f"cannot delete: project still has {', '.join(blockers)}; remove them first"),
            409,
        )

    r = requests.delete(f"{OS_AUTH_URL}/projects/{project_id}", headers=keystone_headers(), timeout=10)
    if r.status_code not in (204, 404):
        r.raise_for_status()
    log.info("deleted project=%s by=%s(%s)", project_id, ident[1], ident[0])
    return "", 204


def _authorize_member_admin(caller_token, project_id):
    """Guard for member list/add/remove/role-change. See the module
    docstring for why this deliberately differs from
    _authorize_project_admin (no immutable block; also accepts a
    domain-scoped admin of the project's own domain).
    Returns ((user_id, user_name), project, None) on success, or
    (None, None, (response, status)) on any failure."""
    ident = validate_caller_token(caller_token)
    if not ident:
        return None, None, (jsonify(error="invalid or expired token"), 401)
    user_id, user_name = ident

    project = _load_target_project(project_id)
    if not project:
        return None, None, (jsonify(error="project not found"), 404)

    if (
        user_has_project_role(user_id, project_id, ADMIN_ROLE)
        or user_has_domain_role(user_id, project["domain_id"], ADMIN_ROLE)
        or user_has_system_admin_role(caller_token, user_id)
    ):
        return (user_id, user_name), project, None

    log.warning("denied member-management project=%s: user=%s missing admin", project_id, user_name)
    return None, None, (jsonify(error="forbidden: you are not admin on this project or its domain"), 403)


def _effective_admin_user_ids(project_id):
    admin_role_id = role_id_by_name(ADMIN_ROLE)
    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"scope.project.id": project_id, "role.id": admin_role_id, "effective": "true"},
        timeout=10,
    )
    r.raise_for_status()
    return {a["user"]["id"] for a in r.json()["role_assignments"] if "user" in a}


def _find_user_by_name(name, domain_id):
    r = requests.get(
        f"{OS_AUTH_URL}/users",
        headers=keystone_headers(),
        params={"name": name, "domain_id": domain_id},
        timeout=10,
    )
    r.raise_for_status()
    users = r.json()["users"]
    return users[0] if users else None


@app.route("/v1/projects/<project_id>/members", methods=["GET"])
def list_members(project_id):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident, project, err = _authorize_member_admin(caller_token, project_id)
    if err:
        return err

    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"scope.project.id": project_id, "effective": "true", "include_names": "true"},
        timeout=10,
    )
    r.raise_for_status()
    members = {}
    for a in r.json()["role_assignments"]:
        if "user" not in a:
            continue  # group-derived grant, not a directly addable/removable member
        uid = a["user"]["id"]
        entry = members.setdefault(uid, {"user_id": uid, "username": a["user"]["name"], "roles": []})
        entry["roles"].append(a["role"]["name"])
    return jsonify(members=list(members.values())), 200


def _k8s_token():
    with open(f"{K8S_SA_DIR}/token") as f:
        return f.read().strip()


def _load_role_bundles():
    """Named bundles of the existing marker/base roles (e.g. "VPC
    Operator" = network-operator + security-operator), so a project
    admin can grant a common combination in one click instead of
    checking several boxes every time. Not a general action-level policy
    engine -- a bundle only ever expands to roles this service already
    understands (see _expand_role_bundles), it can't grant anything
    add_member couldn't already grant directly. Persisted in a
    ConfigMap (see deploy/manifests/project-facade.yaml's Role/
    RoleBinding) rather than in-memory, since this Deployment runs 2
    replicas -- an in-memory dict wouldn't even be consistent between
    them."""
    r = requests.get(
        f"{K8S_API_URL}/api/v1/namespaces/{ROLE_BUNDLES_NAMESPACE}/configmaps/{ROLE_BUNDLES_CONFIGMAP}",
        headers={"Authorization": f"Bearer {_k8s_token()}"},
        verify=f"{K8S_SA_DIR}/ca.crt",
        timeout=10,
    )
    r.raise_for_status()
    data = r.json().get("data") or {}
    return json.loads(data.get("bundles.json") or "{}")


def _save_role_bundles(bundles):
    body = {"data": {"bundles.json": json.dumps(bundles)}}
    r = requests.patch(
        f"{K8S_API_URL}/api/v1/namespaces/{ROLE_BUNDLES_NAMESPACE}/configmaps/{ROLE_BUNDLES_CONFIGMAP}",
        headers={"Authorization": f"Bearer {_k8s_token()}", "Content-Type": "application/strategic-merge-patch+json"},
        json=body,
        verify=f"{K8S_SA_DIR}/ca.crt",
        timeout=10,
    )
    r.raise_for_status()


def _expand_role_bundles(roles):
    """Replace any bundle name in `roles` with its underlying role set,
    leaving ordinary role names untouched. If the ConfigMap can't be
    read for any reason, degrades to a no-op rather than failing the
    whole request -- a name that was genuinely meant to be a bundle then
    just falls through to add_member's normal "invalid role" rejection,
    same as a typo would."""
    try:
        bundles = _load_role_bundles()
    except requests.RequestException:
        return roles
    expanded = set()
    for r in roles:
        expanded.update(bundles[r]["roles"] if r in bundles else [r])
    return sorted(expanded)


@app.route("/v1/role-bundles", methods=["GET"])
def list_role_bundles():
    """Any authenticated user can view bundle definitions -- needed just
    to render what a bundle actually means when selecting one on the Add
    Member form. Viewing isn't the sensitive part; granting one via
    add_member (already domain/project-admin gated) is."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    if not validate_caller_token(caller_token):
        return jsonify(error="invalid or expired token"), 401
    try:
        bundles = _load_role_bundles()
    except requests.RequestException as exc:
        log.warning("role-bundles read failed: %s", exc)
        return jsonify(error="role bundle storage unavailable"), 502
    return jsonify(bundles=bundles), 200


@app.route("/v1/role-bundles/<name>", methods=["PUT"])
def put_role_bundle(name):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, user_name = ident

    domain_id = get_domain_id(OS_DOMAIN_NAME)
    if not domain_id or not (
        user_has_domain_role(user_id, domain_id, ADMIN_ROLE) or user_has_system_admin_role(caller_token, user_id)
    ):
        return jsonify(error="forbidden: you are not an admin of this domain"), 403

    name = name.strip()
    if not name:
        return jsonify(error="bundle name must not be empty"), 400
    if name in ALLOWED_MEMBER_ROLES:
        return jsonify(error=f"'{name}' is already a real role name, can't also be a bundle name"), 400

    body = request.get_json(silent=True) or {}
    description = (body.get("description") or "").strip()
    roles = sorted({(r or "").strip() for r in (body.get("roles") or [])} - {""})
    if not roles:
        return jsonify(error="'roles' must be a non-empty list"), 400
    invalid = [r for r in roles if r not in ALLOWED_MEMBER_ROLES]
    if invalid:
        return jsonify(error=f"invalid role(s) {invalid}; must be one of {sorted(ALLOWED_MEMBER_ROLES)}"), 400

    try:
        bundles = _load_role_bundles()
        bundles[name] = {"description": description, "roles": roles}
        _save_role_bundles(bundles)
    except requests.RequestException as exc:
        log.warning("role-bundles write failed: %s", exc)
        return jsonify(error="role bundle storage unavailable"), 502

    log.info("set role bundle name=%s roles=%s by=%s(%s)", name, roles, user_name, user_id)
    return jsonify(name=name, description=description, roles=roles), 200


@app.route("/v1/role-bundles/<name>", methods=["DELETE"])
def delete_role_bundle(name):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, user_name = ident

    domain_id = get_domain_id(OS_DOMAIN_NAME)
    if not domain_id or not (
        user_has_domain_role(user_id, domain_id, ADMIN_ROLE) or user_has_system_admin_role(caller_token, user_id)
    ):
        return jsonify(error="forbidden: you are not an admin of this domain"), 403

    try:
        bundles = _load_role_bundles()
        if name not in bundles:
            return jsonify(error=f"no such bundle '{name}'"), 404
        del bundles[name]
        _save_role_bundles(bundles)
    except requests.RequestException as exc:
        log.warning("role-bundles delete failed: %s", exc)
        return jsonify(error="role bundle storage unavailable"), 502

    log.info("deleted role bundle name=%s by=%s(%s)", name, user_name, user_id)
    return "", 204


@app.route("/v1/role-bundles/audit-log", methods=["GET"])
def role_bundles_audit_log():
    """Who created/changed/deleted which role bundle, and when -- role
    bundles are domain-scoped (see _load_role_bundles), not tied to any
    one project, so this can't live in a project's own audit-log the way
    every other action in this file does; there would otherwise be
    nowhere in the UI a domain admin could ever see this history at all.
    Domain-admin gated, same as create/delete themselves."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, _user_name = ident

    domain_id = get_domain_id(OS_DOMAIN_NAME)
    if not domain_id or not (
        user_has_domain_role(user_id, domain_id, ADMIN_ROLE) or user_has_system_admin_role(caller_token, user_id)
    ):
        return jsonify(error="forbidden: you are not an admin of this domain"), 403

    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except ValueError:
        return jsonify(error="'limit' must be an integer"), 400

    try:
        # Matches "set role bundle" and "deleted role bundle" (see
        # put_role_bundle/delete_role_bundle's own log.info calls) --
        # "role bundle" alone, not the full prefix, so a single query
        # catches both without needing two round trips.
        streams = _query_loki_lines("role bundle", min(limit * 5, 2000))
    except requests.RequestException as exc:
        log.warning("role-bundles audit-log query failed: %s", exc)
        return jsonify(error="audit log backend unavailable"), 502

    entries = []
    for stream in streams:
        for ts_ns, line in stream.get("values", []):
            m = _LOG_LINE_RE.match(line.strip())
            if not m:
                continue
            level, message = m.groups()
            entries.append(
                {
                    "timestamp": datetime.datetime.fromtimestamp(
                        int(ts_ns) / 1_000_000_000, tz=datetime.timezone.utc
                    ).isoformat(),
                    "level": level,
                    "action": _classify_audit_line(message),
                    "message": message,
                }
            )
    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    return jsonify(entries=entries[:limit]), 200


@app.route("/v1/projects/<project_id>/members", methods=["POST"])
def add_member(project_id):
    """Adds a new member, or -- if the named user is already a member --
    changes their role set instead. Idempotent "set roles" semantics
    rather than purely additive, so this endpoint doubles as the
    project's role editor: re-inviting an existing member with a
    different role set revokes whichever of their old direct
    ALLOWED_MEMBER_ROLES roles on this project aren't in the new set, and
    grants whatever's missing. A caller typically wants a base tier
    (admin/member/reader) plus zero or more capability roles
    (network-operator/security-operator/load-balancer_admin/monitoring)
    together -- e.g. ["member", "network-operator"] -- since the
    capability roles alone don't grant ordinary project CRUD in
    vpc-facade's own authorization classes (see docs/proposals/
    iam-hardening/README.md, "Coordinated implementation direction for
    the VPC platform"). This endpoint doesn't enforce that combination;
    it just sets exactly the roles given."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident, project, err = _authorize_member_admin(caller_token, project_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    roles = sorted({(r or "").strip() for r in (body.get("roles") or [])} - {""})
    # A name here can be a real role or a role-bundle name (see
    # _expand_role_bundles) -- expanded before validation so the rest of
    # this function never has to know the difference.
    roles = _expand_role_bundles(roles)
    if not username:
        return jsonify(error="'username' is required"), 400
    if not roles:
        return jsonify(error="'roles' must be a non-empty list"), 400
    invalid = [r for r in roles if r not in ALLOWED_MEMBER_ROLES]
    if invalid:
        return (
            jsonify(error=f"invalid role(s) {invalid}; must be one of {sorted(ALLOWED_MEMBER_ROLES)}"),
            400,
        )

    target_user = _find_user_by_name(username, project["domain_id"])
    if not target_user:
        return jsonify(error=f"no user named '{username}' found in this domain"), 404

    target_role_ids = {role_id_by_name(r) for r in roles}

    existing = requests.get(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{target_user['id']}/roles",
        headers=keystone_headers(),
        timeout=10,
    )
    existing.raise_for_status()
    existing_roles = existing.json()["roles"]

    if ADMIN_ROLE not in roles and any(r["name"] == ADMIN_ROLE for r in existing_roles):
        admin_ids = _effective_admin_user_ids(project_id)
        if target_user["id"] in admin_ids and len(admin_ids) <= 1:
            return jsonify(error="cannot demote the last admin of this project"), 409

    for r in existing_roles:
        if r["name"] in ALLOWED_MEMBER_ROLES and r["id"] not in target_role_ids:
            rr = requests.delete(
                f"{OS_AUTH_URL}/projects/{project_id}/users/{target_user['id']}/roles/{r['id']}",
                headers=keystone_headers(),
                timeout=10,
            )
            if rr.status_code not in (204, 404):
                rr.raise_for_status()

    existing_names = {r["name"] for r in existing_roles}
    for role_name in roles:
        if role_name in existing_names:
            continue
        grant = requests.put(
            f"{OS_AUTH_URL}/projects/{project_id}/users/{target_user['id']}/roles/{role_id_by_name(role_name)}",
            headers=keystone_headers(),
            timeout=10,
        )
        grant.raise_for_status()

    log.info(
        "set member roles project=%s user=%s(%s) roles=%s by=%s(%s)",
        project_id, username, target_user["id"], roles, ident[1], ident[0],
    )
    status = 201 if not existing_roles else 200
    return jsonify(user_id=target_user["id"], username=username, roles=roles), status


@app.route("/v1/projects/<project_id>/transfer-ownership", methods=["POST"])
def transfer_ownership(project_id):
    """One-click hand-off: grants the named user admin and demotes the
    caller from admin to member in the same request, instead of the two
    manual steps this previously took (change the target's role to
    admin, then separately change your own role or leave). Deliberately
    additive for the target -- their other existing roles are left
    alone, only admin is added -- unlike add_member's "set exact list"
    semantics, since making someone the new owner shouldn't strip
    whatever capability roles they already held.

    Requires the caller to already be a direct or group-derived
    *effective* admin of this exact project, not just a domain admin --
    there's nothing of their own to hand off otherwise. Because this
    always grants the target admin before touching the caller's own
    role, the admin count can never drop to zero mid-transfer, so this
    is exactly the one case that never hits add_member's or leave_
    project's "cannot demote/leave the last admin" guard -- that guard
    exists precisely to force this atomic hand-off instead of a
    demote-then-leave that could momentarily (or permanently, if the
    second step is forgotten) leave the project without an admin."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    caller_id, caller_name = ident

    project = _load_target_project(project_id)
    if not project:
        return jsonify(error="project not found"), 404

    if caller_id not in _effective_admin_user_ids(project_id):
        return jsonify(error="forbidden: you are not an admin of this project"), 403

    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    if not username:
        return jsonify(error="'username' is required"), 400

    target_user = _find_user_by_name(username, project["domain_id"])
    if not target_user:
        return jsonify(error=f"no user named '{username}' found in this domain"), 404
    if target_user["id"] == caller_id:
        return jsonify(error="cannot transfer ownership to yourself"), 400

    admin_role_id = role_id_by_name(ADMIN_ROLE)
    member_role_id = role_id_by_name("member")

    grant = requests.put(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{target_user['id']}/roles/{admin_role_id}",
        headers=keystone_headers(),
        timeout=10,
    )
    grant.raise_for_status()

    revoke = requests.delete(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{caller_id}/roles/{admin_role_id}",
        headers=keystone_headers(),
        timeout=10,
    )
    if revoke.status_code not in (204, 404):
        revoke.raise_for_status()

    caller_roles = requests.get(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{caller_id}/roles",
        headers=keystone_headers(),
        timeout=10,
    )
    caller_roles.raise_for_status()
    if not {r["name"] for r in caller_roles.json()["roles"]} & {"member", "reader"}:
        grant_member = requests.put(
            f"{OS_AUTH_URL}/projects/{project_id}/users/{caller_id}/roles/{member_role_id}",
            headers=keystone_headers(),
            timeout=10,
        )
        grant_member.raise_for_status()

    log.info(
        "transferred ownership project=%s from=%s(%s) to=%s(%s)",
        project_id, caller_name, caller_id, username, target_user["id"],
    )
    return jsonify(new_admin=username), 200


def _revoke_direct_roles(project_id, user_id):
    """Direct (non-effective) assignments only -- these are exactly what
    DELETE .../roles/{role_id} can actually revoke; a role held only via
    group membership isn't removable through this per-user endpoint."""
    r = requests.get(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{user_id}/roles",
        headers=keystone_headers(),
        timeout=10,
    )
    r.raise_for_status()
    for role in r.json()["roles"]:
        rr = requests.delete(
            f"{OS_AUTH_URL}/projects/{project_id}/users/{user_id}/roles/{role['id']}",
            headers=keystone_headers(),
            timeout=10,
        )
        if rr.status_code not in (204, 404):
            rr.raise_for_status()


@app.route("/v1/projects/<project_id>/members/<user_id>", methods=["DELETE"])
def remove_member(project_id, user_id):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident, project, err = _authorize_member_admin(caller_token, project_id)
    if err:
        return err

    # Refuse to strip the project's last admin, effective (including any
    # group-derived) grants included -- otherwise a project could be
    # locked out of its own self-service management entirely, with no
    # break-glass path back in short of a platform admin.
    admin_user_ids = _effective_admin_user_ids(project_id)
    if user_id in admin_user_ids and len(admin_user_ids) <= 1:
        return jsonify(error="cannot remove the last admin of this project"), 409

    _revoke_direct_roles(project_id, user_id)
    log.info("removed member project=%s user=%s by=%s(%s)", project_id, user_id, ident[1], ident[0])
    return "", 204


@app.route("/v1/projects/<project_id>/leave", methods=["POST"])
def leave_project(project_id):
    """Lets any authenticated user remove themselves from a project they
    hold a direct role on. Deliberately no admin check at all, unlike
    every other member-management endpoint above -- leaving a project is
    something a member should always be able to do for themselves,
    without needing anyone else's permission, the same way a platform
    doesn't normally require someone else's approval to quit a team.
    Still refuses if the caller is the project's last admin (the same
    protection remove_member has), so a project can never be abandoned
    with no one left able to manage it -- the caller must hand off
    ownership (change someone else's role to admin) before leaving."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, user_name = ident

    project = _load_target_project(project_id)
    if not project:
        return jsonify(error="project not found"), 404

    admin_user_ids = _effective_admin_user_ids(project_id)
    if user_id in admin_user_ids and len(admin_user_ids) <= 1:
        return jsonify(error="cannot leave: you are the last admin of this project"), 409

    _revoke_direct_roles(project_id, user_id)
    log.info("left project project=%s user=%s(%s)", project_id, user_name, user_id)
    return "", 204


# logging.basicConfig's default format is "LEVEL:logger name:message" --
# matching that here is what separates real audit log lines from the app
# server's separate, unrelated access-log stream (gunicorn's own request
# logging, which has no such prefix and would otherwise also match the
# plain-project_id substring filter in _query_loki_project_lines, e.g.
# "POST /v1/projects/<id>/members HTTP/1.1 201").
_LOG_LINE_RE = re.compile(r"^(INFO|WARNING|ERROR):project-facade:(.*)$")

# Prefixes of the log.info/log.warning calls above, in the order they're
# checked -- first match wins. Denials are classified by their own
# "denied ..." prefix regardless of which action they're denying, since
# the message text after that already says which.
_AUDIT_LINE_PREFIXES = (
    ("denied", "denied"),
    ("created project", "create_project"),
    ("updated project", "update_project"),
    ("deleted project", "delete_project"),
    ("set member roles", "set_member_roles"),
    ("removed member", "remove_member"),
    ("left project", "leave_project"),
    ("transferred ownership", "transfer_ownership"),
    ("vpc-facade audit merge failed", "vpc_facade_unavailable"),
    ("set role bundle", "set_role_bundle"),
    ("deleted role bundle", "delete_role_bundle"),
)


def _classify_audit_line(message):
    for prefix, action in _AUDIT_LINE_PREFIXES:
        if message.startswith(prefix):
            return action
    return "other"


def _query_loki_lines(match_string, limit):
    # Filtering on a bare substring (rather than trying to match every
    # log line's differently-named key -- some use `project=`, created
    # project uses `id=`) is deliberate: project ids are high-entropy
    # UUIDs, so a substring match is already effectively exact, and it
    # matches every current and future log line mentioning it without
    # having to keep this query in sync with every log statement's
    # format. Also reused for non-project-id substrings (see
    # role_bundles_audit_log) since the same reasoning applies to any
    # sufficiently distinctive string.
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - AUDIT_LOG_LOOKBACK_SECONDS * 1_000_000_000
    query = '{job="%s"} |= `%s`' % (LOKI_JOB_LABEL, match_string)
    r = requests.get(
        f"{LOKI_URL}/loki/api/v1/query_range",
        params={
            "query": query,
            "start": start_ns,
            "end": end_ns,
            "limit": limit,
            "direction": "backward",
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["data"]["result"]


# Other core OpenStack services this cluster runs also log through
# oslo.log/oslo.context, which stamps every request-scoped log line with
# a bracketed context -- "[<req-id(s)> <user_id> <project_id> - - <user
# domain> <project domain>] <message>" -- regardless of which service
# emits it. Parsed generically here rather than per-service, since the
# bracket shape is the same everywhere (Neutron's pecan/wsgi stack
# prefixes two req- ids instead of one; the regex doesn't care how many
# tokens precede the two 32-hex user/project ids, just that they're
# followed by " - - ").
#
# Coverage genuinely varies a lot by service, confirmed live rather than
# assumed:
# - Cinder's WSGI middleware logs a clean "METHOD <url>" request line and
#   a "<url> returned with HTTP <status>" response line for every API
#   call at INFO -- complete coverage.
# - Nova and Neutron mostly only surface this bracketed context on
#   errors/exceptions at INFO (their routine successful-request logging
#   is at DEBUG, not enabled in this deployment) -- real entries, but
#   skewed toward failures, not a full request history.
# - Glance emits essentially nothing with this context at INFO (zero
#   matches over a full week, confirmed live) and isn't wired up at all.
# Raising any of these services' own log level cluster-wide to get
# fuller coverage is a separate, bigger tradeoff (log volume, storage
# cost, unrelated to this project's own audit trail) out of scope here.
_OSLO_CONTEXT_LINE_RE = re.compile(r"\[[^\]]*?([0-9a-f]{32}) ([0-9a-f]{32}) - - [^\]]*\]\s*(.*)$")
_MUTATING_HTTP_VERBS = ("POST", "PUT", "DELETE", "PATCH")
_OPENSTACK_AUDIT_SOURCES = (
    ("openstack/cinder-api", "cinder"),
    ("openstack/nova-osapi", "nova"),
    ("openstack/neutron-server", "neutron"),
)


def _is_audit_worthy_service_line(message):
    """Filters request-line noise down to what's actually worth showing:
    an attempted mutation (regardless of outcome) or any line that reads
    as a failure/exception, regardless of verb -- plain successful GETs
    and plain 200 "returned with HTTP" response lines are excluded, both
    because they'd otherwise dominate the feed and because a bare
    response line doesn't even carry the original method to classify."""
    for verb in _MUTATING_HTTP_VERBS:
        if message.startswith(verb + " "):
            return True
    lowered = message.lower()
    return "exception" in lowered or "failed" in lowered or " error" in lowered


def _classify_openstack_service_line(message):
    for verb in _MUTATING_HTTP_VERBS:
        if message.startswith(verb + " "):
            return verb.lower()
    return "denied_or_failed"


def _openstack_service_audit_entries(project_id, limit):
    """Merges in the mutating/failed-request slice of Cinder/Nova/
    Neutron's own oslo.log output for this project -- see the constants
    above for exactly what that does and doesn't cover. Uses this
    service's own domain-scoped credential is irrelevant here (Loki has
    no per-project authorization of its own; this project_id-substring
    filter is what actually scopes results, same as
    _query_loki_project_lines for this service's own logs)."""
    entries = []
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - AUDIT_LOG_LOOKBACK_SECONDS * 1_000_000_000
    for job_label, source in _OPENSTACK_AUDIT_SOURCES:
        query = '{job="%s"} |= "%s"' % (job_label, project_id)
        try:
            r = requests.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "start": start_ns,
                    "end": end_ns,
                    "limit": min(limit * 5, 2000),
                    "direction": "backward",
                },
                timeout=10,
            )
            r.raise_for_status()
            streams = r.json()["data"]["result"]
        except requests.RequestException as exc:
            log.warning("%s audit merge failed project=%s: %s", source, project_id, exc)
            continue
        for stream in streams:
            for ts_ns, line in stream.get("values", []):
                m = _OSLO_CONTEXT_LINE_RE.search(line.strip())
                if not m:
                    continue
                _user_id, proj, message = m.groups()
                if proj != project_id or not _is_audit_worthy_service_line(message):
                    continue
                entries.append(
                    {
                        "timestamp": datetime.datetime.fromtimestamp(
                            int(ts_ns) / 1_000_000_000, tz=datetime.timezone.utc
                        ).isoformat(),
                        "level": "WARNING" if _classify_openstack_service_line(message) == "denied_or_failed" else "INFO",
                        "action": _classify_openstack_service_line(message),
                        "message": message,
                        "source": source,
                    }
                )
    return entries


def _vpc_facade_audit_entries(caller_token, project_id, limit):
    """vpc-facade's own /v1/audit -- Kubernetes Events plus SecurityGroup/
    ElasticIP/NetworkInterface status history, richer than anything this
    service could derive from its own request logs -- merged in here so
    a project's identity/membership history and its VPC/network history
    show up in one place. Deliberately forwards the CALLER's own token
    rather than this service's admin credential: vpc-facade scopes that
    endpoint to the caller's own accessible namespaces
    (scope.Namespaces), which could include projects beyond the one
    requested (a domain-scoped caller sees their whole domain) -- so
    results are filtered here to exactly this project_id rather than
    trusting vpc-facade's response set as already scoped correctly for
    this purpose. Best-effort: an unreachable or erroring vpc-facade
    just means fewer entries, not a failed request -- this project's own
    audit history is still worth showing on its own."""
    try:
        r = requests.get(
            f"{VPC_FACADE_URL}/v1/audit",
            headers={"X-Auth-Token": caller_token},
            params={"limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        raw_entries = r.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("vpc-facade audit merge failed project=%s: %s", project_id, exc)
        return []

    mapped = []
    for e in raw_entries or []:
        if e.get("projectID") != project_id:
            continue
        ts_raw = e.get("time") or ""
        try:
            timestamp = datetime.datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).isoformat()
        except ValueError:
            timestamp = ts_raw
        detail_parts = [p for p in (e.get("detail"), e.get("before"), e.get("after")) if p]
        message = f"{e.get('kind', '')}/{e.get('name', '')}: {e.get('action', '')}"
        if detail_parts:
            message += " (" + "; ".join(detail_parts) + ")"
        mapped.append(
            {
                "timestamp": timestamp,
                "level": "WARNING" if e.get("outcome") == "failed" else "INFO",
                "action": e.get("action") or "other",
                "message": message,
                "source": "vpc-facade",
            }
        )
    return mapped


@app.route("/v1/projects/<project_id>/audit-log", methods=["GET"])
def project_audit_log(project_id):
    """Read-only audit trail of self-service actions taken against this
    project -- create/update/delete, member add/change/remove, leave,
    including denied attempts -- sourced from this service's own request
    logs via Loki rather than a separate datastore (every mutating action
    above already logs project id, actor, and outcome), merged with
    vpc-facade's own richer audit history for the same project (see
    _vpc_facade_audit_entries). Same admin-or-domain-admin authorization
    as member management (_authorize_member_admin): this exposes who did
    what to the project, which is at least as sensitive as the
    membership list itself."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401

    _, _, err = _authorize_member_admin(caller_token, project_id)
    if err:
        return err

    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except ValueError:
        return jsonify(error="'limit' must be an integer"), 400

    try:
        # Over-fetch: most lines Loki matches on the bare project_id
        # substring are this service's own unrelated access-log traffic
        # (e.g. this very audit-log request, or a GET .../members poll),
        # filtered out by _LOG_LINE_RE above, not the audit lines
        # themselves -- asking Loki for exactly `limit` raw lines would
        # often return far fewer than `limit` real audit entries.
        streams = _query_loki_lines(project_id, min(limit * 5, 2000))
    except requests.RequestException as exc:
        log.warning("audit-log query failed project=%s: %s", project_id, exc)
        return jsonify(error="audit log backend unavailable"), 502

    entries = []
    for stream in streams:
        for ts_ns, line in stream.get("values", []):
            m = _LOG_LINE_RE.match(line.strip())
            if not m:
                continue
            level, message = m.groups()
            entries.append(
                {
                    "timestamp": datetime.datetime.fromtimestamp(
                        int(ts_ns) / 1_000_000_000, tz=datetime.timezone.utc
                    ).isoformat(),
                    "level": level,
                    "action": _classify_audit_line(message),
                    "message": message,
                    "source": "project-facade",
                }
            )
    entries.extend(_vpc_facade_audit_entries(caller_token, project_id, limit))
    entries.extend(_openstack_service_audit_entries(project_id, limit))
    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    entries = entries[:limit]

    if request.args.get("format", "").lower() == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["timestamp", "level", "action", "source", "message"])
        for e in entries:
            writer.writerow([e["timestamp"], e["level"], e["action"], e["source"], e["message"]])
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="project-{project_id}-audit-log.csv"'},
        )

    return jsonify(entries=entries)


@app.route("/v1/domain-admin", methods=["GET"])
def check_domain_admin():
    """Tells a caller whether *they* hold `admin` at domain scope on the
    one domain this service administers (OS_DOMAIN_NAME). Added so Horizon
    can determine real domain-admin status for UI-visibility decisions
    (Identity dashboard panels, admin-only table actions) without relying
    on its own broken mechanism -- see docs/proposals/iam-hardening/
    README.md, "New permission tier: self-service project lifecycle",
    for why: Horizon's stock is_domain_admin() needs a domain-scoped token
    cached in the session, which openstack_auth never sets when
    SESSION_ENGINE is signed_cookies (this deployment's session backend,
    chosen for an unrelated multi-replica session bug -- a domain token
    doesn't fit in a cookie), so it silently fell back to evaluating an
    undefined Horizon-local policy rule that fails open for everyone.
    This endpoint sidesteps that entirely: it uses the caller's own
    (whatever-scope) token just to identify who they are, then answers the
    question itself via user_has_domain_role(), which already correctly
    resolves group-derived (federated) role membership -- the same check
    create_project() uses for the project-creator role. Also true for the
    real cloud-wide administrator (user_has_system_admin_role) even
    though they hold no direct or group-derived grant on this specific
    domain -- see that function's docstring."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, _user_name = ident

    domain_id = get_domain_id(OS_DOMAIN_NAME)
    is_admin = (bool(domain_id) and user_has_domain_role(user_id, domain_id, ADMIN_ROLE)) or user_has_system_admin_role(
        caller_token, user_id
    )
    return jsonify(is_domain_admin=is_admin, domain=OS_DOMAIN_NAME), 200


@app.route("/v1/projects/<project_id>/simulate-access", methods=["GET"])
def simulate_access(project_id):
    """Dry-run breakdown of what the caller can actually do to this
    project right now, one line per gated action, reusing the exact same
    checks each real endpoint enforces -- not a hypothetical "what if I
    had role X" evaluator (that would need a synthetic identity threaded
    through every check below, a much bigger change), but a genuine
    answer to "why can/can't I do this" without having to actually
    attempt each action and read its error. No authorization beyond a
    valid token: this only ever evaluates the caller's own real access,
    never someone else's.

    `delete_project`'s True/False here reflects only its admin/immutable
    gate -- the real endpoint also refuses to delete a project with
    active Nova/Cinder/Neutron resources, which isn't cheap to check and
    isn't duplicated here; a True from this endpoint means "you have
    permission to attempt it", not "it's guaranteed to succeed"."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, _user_name = ident

    project = _load_target_project(project_id)
    if not project:
        return jsonify(error="project not found"), 404

    is_project_admin = user_has_project_role(user_id, project_id, ADMIN_ROLE)
    is_domain_admin = user_has_domain_role(user_id, project["domain_id"], ADMIN_ROLE) or user_has_system_admin_role(
        caller_token, user_id
    )
    is_member_admin_eligible = is_project_admin or is_domain_admin  # _authorize_member_admin's rule
    immutable = bool(project.get("options", {}).get("immutable"))
    admin_ids = _effective_admin_user_ids(project_id)
    is_last_admin = user_id in admin_ids and len(admin_ids) <= 1
    has_any_role = bool(user_has_project_role(user_id, project_id, "member")
                         or user_has_project_role(user_id, project_id, "reader")
                         or user_id in admin_ids)

    actions = {
        "manage_members": is_member_admin_eligible,
        "view_audit_log": is_member_admin_eligible,
        "transfer_ownership": user_id in admin_ids,
        "update_project": is_project_admin and not immutable,
        "delete_project": is_project_admin and not immutable,
        "leave_project": has_any_role and not is_last_admin,
    }
    reasons = {}
    if not is_member_admin_eligible:
        reasons["manage_members"] = reasons["view_audit_log"] = "not admin on this project or its domain"
    if user_id not in admin_ids:
        reasons["transfer_ownership"] = "not an admin of this project"
    if immutable:
        reasons["update_project"] = reasons["delete_project"] = "project is protected (immutable)"
    elif not is_project_admin:
        reasons["update_project"] = reasons["delete_project"] = "not project-scoped admin (domain admin doesn't qualify here)"
    if not has_any_role:
        reasons["leave_project"] = "you have no role on this project to leave"
    elif is_last_admin:
        reasons["leave_project"] = "you are the last admin of this project"

    return jsonify(project_id=project_id, actions=actions, reasons=reasons), 200


@app.route("/v1/my-access", methods=["GET"])
def my_access():
    """Every project in this service's domain the caller has *any*
    effective access to (direct or group-derived), with their role(s) on
    each -- the thing a stock Keystone/Horizon session token can't answer
    on its own without walking every project one at a time. Reuses the
    exact same `role_assignments?...&effective=true` mechanism
    `list_members` already relies on for correct group-derived
    visibility, just filtered by the caller's own user id instead of a
    project id. No special authorization beyond a valid token -- this is
    always a user looking at their own access, never someone else's."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, _user_name = ident

    domain_id = get_domain_id(OS_DOMAIN_NAME)

    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"user.id": user_id, "effective": "true", "include_names": "true"},
        timeout=10,
    )
    r.raise_for_status()

    roles_by_project = {}
    for a in r.json()["role_assignments"]:
        project = a.get("scope", {}).get("project")
        if not project:
            continue  # domain- or system-scoped grant, not project membership
        roles_by_project.setdefault(project["id"], set()).add(a["role"]["name"])

    projects = []
    for project_id, roles in roles_by_project.items():
        project = _load_target_project(project_id)
        # Only this service's own domain -- a user could in principle
        # have grants on projects in other domains this service doesn't
        # administer, and it has no way to resolve those names correctly.
        if not project or project["domain_id"] != domain_id:
            continue
        projects.append({"project_id": project_id, "project_name": project["name"], "roles": sorted(roles)})
    projects.sort(key=lambda p: p["project_name"])
    return jsonify(projects=projects), 200


def _project_member_summary(project_id):
    """(admin usernames, total effective member count) for one project --
    same role_assignments call list_members makes, reduced down for an
    overview table rather than a full per-member breakdown."""
    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"scope.project.id": project_id, "effective": "true", "include_names": "true"},
        timeout=10,
    )
    r.raise_for_status()
    admins, members = set(), set()
    for a in r.json()["role_assignments"]:
        if "user" not in a:
            continue
        members.add(a["user"]["id"])
        if a["role"]["name"] == ADMIN_ROLE:
            admins.add(a["user"]["name"])
    return sorted(admins), len(members)


def _domain_last_activity_by_project(lookback_lines=1000):
    """Best-effort last-touched timestamp per project, for the overview
    table below -- one broad Loki query across every project's log
    lines rather than one query per project (which would be an N+1
    Loki call for every project in the domain on every page load).
    Extracts the project id from each line via the same 32-hex-character
    Keystone id shape every id in this service already has, rather than
    trying to match a specific key name (see _query_loki_project_lines
    for the same reasoning applied to a single project)."""
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = end_ns - AUDIT_LOG_LOOKBACK_SECONDS * 1_000_000_000
    query = '{job="%s"} |= "project-facade:"' % LOKI_JOB_LABEL
    try:
        r = requests.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": start_ns,
                "end": end_ns,
                "limit": lookback_lines,
                "direction": "backward",
            },
            timeout=10,
        )
        r.raise_for_status()
        streams = r.json()["data"]["result"]
    except requests.RequestException:
        return {}

    latest = {}
    for stream in streams:
        for ts_ns, line in stream.get("values", []):
            m = _LOG_LINE_RE.match(line.strip())
            if not m:
                continue
            pid_match = re.search(r"[0-9a-f]{32}", m.group(2))
            if not pid_match:
                continue
            pid = pid_match.group(0)
            iso = datetime.datetime.fromtimestamp(int(ts_ns) / 1_000_000_000, tz=datetime.timezone.utc).isoformat()
            if pid not in latest or iso > latest[pid]:
                latest[pid] = iso
    return latest


@app.route("/v1/domain-projects-overview", methods=["GET"])
def domain_projects_overview():
    """Every project in this service's domain, with its admin(s), member
    count, and last self-service activity -- the domain-wide view a
    domain admin currently has no way to get without opening each
    project's Manage Members panel one at a time. Same domain-admin
    authorization as check_domain_admin (user_has_domain_role), since
    this exposes membership summaries across every project in the
    domain, not just one a caller already administers."""
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident = validate_caller_token(caller_token)
    if not ident:
        return jsonify(error="invalid or expired token"), 401
    user_id, _user_name = ident

    domain_id = get_domain_id(OS_DOMAIN_NAME)
    if not domain_id or not (
        user_has_domain_role(user_id, domain_id, ADMIN_ROLE) or user_has_system_admin_role(caller_token, user_id)
    ):
        return jsonify(error="forbidden: you are not an admin of this domain"), 403

    r = requests.get(
        f"{OS_AUTH_URL}/projects", headers=keystone_headers(), params={"domain_id": domain_id}, timeout=10
    )
    r.raise_for_status()
    last_activity = _domain_last_activity_by_project()

    overview = []
    for project in r.json()["projects"]:
        admins, member_count = _project_member_summary(project["id"])
        overview.append(
            {
                "project_id": project["id"],
                "project_name": project["name"],
                "admins": admins,
                "member_count": member_count,
                "last_activity": last_activity.get(project["id"]),
            }
        )
    overview.sort(key=lambda p: p["project_name"])
    return jsonify(projects=overview), 200


@app.route("/healthz")
def healthz():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
