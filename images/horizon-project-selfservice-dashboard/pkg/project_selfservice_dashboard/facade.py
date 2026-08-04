"""Thin HTTP client for the project-facade self-service project lifecycle
API (see docs/proposals/iam-hardening/README.md, "New permission tier:
self-service project lifecycle"). This module never holds any elevated
credential of its own -- every call forwards the logged-in user's own
Horizon session token, so authorization is enforced entirely by
project-facade itself against Keystone, exactly as it would be for a
caller hitting the API directly. Horizon only decides what to *show*; it
is never the source of authorization (see "Authority boundaries" in the
same doc: "UI visibility is never treated as authorization").

Reached over the internal cluster Service, not the public Gateway route --
this is a server-to-server call from within the same namespace.
"""

import requests
from django.utils.translation import gettext_lazy as _

PROJECT_FACADE_URL = "http://project-facade.openstack.svc.cluster.local:8080"
_TIMEOUT = 15
# Shorter than _TIMEOUT above: is_domain_admin() runs on ordinary page
# renders (panel visibility, row-action gating), not a form submission --
# a slow/unreachable project-facade must fail fast, not stall every page.
_DOMAIN_ADMIN_TIMEOUT = 5


class FacadeError(Exception):
    """Raised with a message already safe to show the end user."""


def _headers(request):
    return {"X-Auth-Token": request.user.token.id, "Content-Type": "application/json"}


def _error_message(response):
    try:
        return response.json().get("error") or response.text
    except ValueError:
        return response.text or f"HTTP {response.status_code}"


def create_project(request, name, description):
    try:
        r = requests.post(
            f"{PROJECT_FACADE_URL}/v1/projects",
            headers=_headers(request),
            json={"name": name, "description": description},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    if r.status_code != 201:
        raise FacadeError(_error_message(r))
    return r.json()


def update_project(request, project_id, **fields):
    try:
        r = requests.patch(
            f"{PROJECT_FACADE_URL}/v1/projects/{project_id}",
            headers=_headers(request),
            json=fields,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    if r.status_code != 200:
        raise FacadeError(_error_message(r))
    return r.json()


def delete_project(request, project_id):
    try:
        r = requests.delete(
            f"{PROJECT_FACADE_URL}/v1/projects/{project_id}",
            headers=_headers(request),
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    if r.status_code not in (204, 404):
        raise FacadeError(_error_message(r))


def list_members(request, project_id):
    try:
        r = requests.get(
            f"{PROJECT_FACADE_URL}/v1/projects/{project_id}/members",
            headers=_headers(request),
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    if r.status_code != 200:
        raise FacadeError(_error_message(r))
    return r.json()["members"]


def add_member(request, project_id, username, roles):
    try:
        r = requests.post(
            f"{PROJECT_FACADE_URL}/v1/projects/{project_id}/members",
            headers=_headers(request),
            json={"username": username, "roles": list(roles)},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    # 201 for a brand-new member, 200 when the named user was already a
    # member and this call changed their role set instead (see
    # project-facade app.py's add_member -- idempotent "set roles"
    # semantics).
    if r.status_code not in (200, 201):
        raise FacadeError(_error_message(r))
    return r.json()


def is_domain_admin(request):
    """Replacement for openstack_dashboard.api.keystone.is_domain_admin,
    installed over the original at Django startup by
    ProjectSelfserviceDashboardConfig.ready() (see apps.py) -- monkeypatch,
    not a copy of that (large, widely-imported) file. Confirmed live that
    every caller (identity/{projects,users,groups,roles,credentials}
    panels/tables, plus keystone.py's own keystoneclient(admin=True))
    invokes it as a module-attribute lookup (`keystone.is_domain_admin(...)`
    or, from within keystone.py itself, a bare call resolved from the same
    module globals at call time), so replacing the attribute on the module
    object reaches every one of them.

    The stock implementation asks a Horizon-local policy rule
    ("admin_and_matching_domain_id") that (a) isn't defined anywhere in
    this deployment's policy files, so openstack_auth.policy.check()'s
    documented fail-open behavior for undefined rules makes it always
    True regardless, and (b) even if defined, is only ever evaluated
    against the caller's *project*-scoped credentials here: a domain-
    scoped token would be needed for the real domain-scope evaluation,
    and openstack_auth deliberately never caches one in the session when
    SESSION_ENGINE is signed_cookies (this deployment's session backend --
    a domain token doesn't fit in a cookie), logging an error and skipping
    it instead. Both confirmed live, not assumed.

    Fixed by asking project-facade instead, which already holds a
    domain-scoped credential and already correctly resolves group-derived
    (federated) role membership for exactly this kind of question -- the
    same logic create_project() uses to check the project-creator role.
    Fails closed (False) on any error or unreachable facade, since this
    now gates real UI-visibility decisions (Identity dashboard panels,
    admin-only table actions) rather than the previous always-True
    default.
    """
    cache_attr = "_dcn_is_domain_admin"
    if hasattr(request, cache_attr):
        return getattr(request, cache_attr)

    result = False
    token = getattr(getattr(request, "user", None), "token", None)
    token_id = getattr(token, "id", None)
    if token_id:
        try:
            r = requests.get(
                f"{PROJECT_FACADE_URL}/v1/domain-admin",
                headers={"X-Auth-Token": token_id},
                timeout=_DOMAIN_ADMIN_TIMEOUT,
            )
            if r.status_code == 200:
                result = bool(r.json().get("is_domain_admin"))
        except requests.RequestException:
            result = False

    setattr(request, cache_attr, result)
    return result


def remove_member(request, project_id, user_id):
    try:
        r = requests.delete(
            f"{PROJECT_FACADE_URL}/v1/projects/{project_id}/members/{user_id}",
            headers=_headers(request),
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    if r.status_code not in (204, 404):
        raise FacadeError(_error_message(r))


def leave_project(request, project_id):
    try:
        r = requests.post(
            f"{PROJECT_FACADE_URL}/v1/projects/{project_id}/leave",
            headers=_headers(request),
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    if r.status_code not in (204, 404):
        raise FacadeError(_error_message(r))


def audit_log(request, project_id, limit=100):
    try:
        r = requests.get(
            f"{PROJECT_FACADE_URL}/v1/projects/{project_id}/audit-log",
            headers=_headers(request),
            params={"limit": limit},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise FacadeError(_("Could not reach the project service: %s") % exc) from exc
    if r.status_code != 200:
        raise FacadeError(_error_message(r))
    return r.json()["entries"]
