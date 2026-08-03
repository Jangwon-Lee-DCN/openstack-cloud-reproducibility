"""project-facade: self-service Keystone project lifecycle API.

Lets a user holding the domain-scoped `project-creator` marker role create
their own project under that domain, automatically becoming full `admin`
on the project they just created. Update/delete of any project requires
the caller to already be project-scoped `admin` on that specific project,
and refuses outright if the project has Keystone's `options.immutable`
flag set (used to protect a domain's designated admin project, e.g. `dcn`
in the `dcn` domain -- see docs/proposals/iam-hardening/README.md, "New
permission tier: self-service project lifecycle").

Also lets that same project admin manage who else has access to their own
project (add/remove members, admin/member/reader) -- the natural next
step once a project can be self-service-created at all: someone who owns
a project needs to be able to invite teammates into it without asking a
platform admin every time. Same authorization boundary as update/delete
(caller must be project-scoped admin on that exact project); additionally
refuses to remove a project's last remaining admin, so a project can never
be locked out of its own self-service management.

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

import datetime
import logging
import os
import time

import requests
from flask import Flask, jsonify, request

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

PROJECT_CREATOR_ROLE = "project-creator"
ADMIN_ROLE = "admin"
ALLOWED_MEMBER_ROLES = {"admin", "member", "reader"}

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
    ident, err = _authorize_project_admin(caller_token, project_id)
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


@app.route("/v1/projects/<project_id>/members", methods=["POST"])
def add_member(project_id):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident, err = _authorize_project_admin(caller_token, project_id)
    if err:
        return err

    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    role_name = (body.get("role") or "member").strip()
    if not username:
        return jsonify(error="'username' is required"), 400
    if role_name not in ALLOWED_MEMBER_ROLES:
        return jsonify(error=f"'role' must be one of {sorted(ALLOWED_MEMBER_ROLES)}"), 400

    project = _load_target_project(project_id)
    target_user = _find_user_by_name(username, project["domain_id"])
    if not target_user:
        return jsonify(error=f"no user named '{username}' found in this domain"), 404

    role_id = role_id_by_name(role_name)
    r = requests.put(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{target_user['id']}/roles/{role_id}",
        headers=keystone_headers(),
        timeout=10,
    )
    r.raise_for_status()
    log.info(
        "added member project=%s user=%s(%s) role=%s by=%s(%s)",
        project_id, username, target_user["id"], role_name, ident[1], ident[0],
    )
    return jsonify(user_id=target_user["id"], username=username, role=role_name), 201


@app.route("/v1/projects/<project_id>/members/<user_id>", methods=["DELETE"])
def remove_member(project_id, user_id):
    caller_token = request.headers.get("X-Auth-Token")
    if not caller_token:
        return jsonify(error="missing X-Auth-Token header"), 401
    ident, err = _authorize_project_admin(caller_token, project_id)
    if err:
        return err

    admin_role_id = role_id_by_name(ADMIN_ROLE)

    # Refuse to strip the project's last admin, effective (including any
    # group-derived) grants included -- otherwise a project could be
    # locked out of its own self-service management entirely, with no
    # break-glass path back in short of a platform admin.
    r = requests.get(
        f"{OS_AUTH_URL}/role_assignments",
        headers=keystone_headers(),
        params={"scope.project.id": project_id, "role.id": admin_role_id, "effective": "true"},
        timeout=10,
    )
    r.raise_for_status()
    admin_user_ids = {a["user"]["id"] for a in r.json()["role_assignments"] if "user" in a}
    if user_id in admin_user_ids and len(admin_user_ids) <= 1:
        return jsonify(error="cannot remove the last admin of this project"), 409

    # Direct (non-effective) assignments only -- these are exactly what
    # DELETE .../roles/{role_id} can actually revoke; a role held only via
    # group membership isn't removable through this per-user endpoint.
    r2 = requests.get(
        f"{OS_AUTH_URL}/projects/{project_id}/users/{user_id}/roles",
        headers=keystone_headers(),
        timeout=10,
    )
    r2.raise_for_status()
    for role in r2.json()["roles"]:
        rr = requests.delete(
            f"{OS_AUTH_URL}/projects/{project_id}/users/{user_id}/roles/{role['id']}",
            headers=keystone_headers(),
            timeout=10,
        )
        if rr.status_code not in (204, 404):
            rr.raise_for_status()

    log.info("removed member project=%s user=%s by=%s(%s)", project_id, user_id, ident[1], ident[0])
    return "", 204


@app.route("/healthz")
def healthz():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
