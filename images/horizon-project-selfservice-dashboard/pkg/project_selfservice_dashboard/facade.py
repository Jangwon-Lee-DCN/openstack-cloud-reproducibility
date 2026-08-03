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
