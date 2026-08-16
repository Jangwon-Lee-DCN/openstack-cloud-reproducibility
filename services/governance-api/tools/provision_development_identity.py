#!/usr/bin/env python3
"""Idempotently provision the isolated governance development identity.

Reads the Kubernetes keystone admin Secret JSON on stdin and writes only a
Kubernetes Secret manifest on stdout. It never logs credential material.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def decode(data, key):
    return base64.b64decode(data[key]).decode()


def call(url, token="", method="GET", body=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Auth-Token"] = token
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, separators=(",", ":")).encode()
    request = Request(url, data=payload, method=method, headers=headers)
    with urlopen(request, timeout=10) as response:
        return response.headers, json.loads(response.read() or b"{}")


def password_token(base, username, password, project, domain):
    body = {"auth": {"identity": {"methods": ["password"], "password": {"user": {
        "name": username, "password": password, "domain": {"name": domain}}}},
        "scope": {"project": {"name": project, "domain": {"name": domain}}}}}
    headers, document = call(base + "/auth/tokens", method="POST", body=body)
    return headers["X-Subject-Token"], document


def one_or_create(base, token, collection, key, value, create_body):
    _, result = call(f"{base}/{collection}?{urlencode({key: value})}", token)
    singular = {"projects": "project", "users": "user"}[collection]
    items = result.get(collection, [])
    if items:
        return items[0]
    return call(f"{base}/{collection}", token, "POST", {singular: create_body})[1][singular]


def b64(value):
    return base64.b64encode(value.encode()).decode()


def rotate_application_credential(base, admin_token, user, password, project, domain):
    _, existing = call(f"{base}/users/{user['id']}/application_credentials", admin_token)
    for credential in existing.get("application_credentials", []):
        if credential.get("name") == "governance-development":
            call(f"{base}/users/{user['id']}/application_credentials/{credential['id']}",
                 admin_token, "DELETE")
    # Deleting an application credential records a user revocation event. Get
    # the password-scoped token only after the old credential is gone so the
    # token used for replacement creation cannot be invalidated mid-rotation.
    user_token, _ = password_token(base, user["name"], password, project["name"], domain)
    _, created = call(f"{base}/users/{user['id']}/application_credentials", user_token, "POST",
                      {"application_credential": {"name": "governance-development",
                       "description": "Track B development-only provider probes", "unrestricted": False}})
    return created["application_credential"]


def main():
    source = json.load(sys.stdin)["data"]
    base = os.environ["GOVERNANCE_KEYSTONE_BOOTSTRAP_URL"].rstrip("/") + "/v3"
    domain = decode(source, "OS_DEFAULT_DOMAIN")
    admin_token, _ = password_token(base, decode(source, "OS_USERNAME"),
                                    decode(source, "OS_PASSWORD"),
                                    decode(source, "OS_PROJECT_NAME"), domain)
    _, domains = call(f"{base}/domains?{urlencode({'name': domain})}", admin_token)
    domain_id = domains["domains"][0]["id"]
    project = one_or_create(base, admin_token, "projects", "name", "governance-development",
                            {"name": "governance-development", "domain_id": domain_id,
                             "description": "Track B isolated real-integration acceptance", "enabled": True})
    password = secrets.token_urlsafe(32)
    user = one_or_create(base, admin_token, "users", "name", "governance-development",
                         {"name": "governance-development", "domain_id": domain_id,
                          "default_project_id": project["id"], "password": password, "enabled": True})
    # Rotate the bootstrap password on every reprovision; it is never persisted.
    call(f"{base}/users/{user['id']}", admin_token, "PATCH", {"user": {"password": password}})
    _, role_doc = call(base + "/roles", admin_token)
    roles = {role["name"]: role["id"] for role in role_doc["roles"]}
    if "creator" not in roles:
        _, created_role = call(base + "/roles", admin_token, "POST", {"role": {"name": "creator"}})
        roles["creator"] = created_role["role"]["id"]
    assigned = []
    for name in ("reader", "member", "load-balancer_member", "creator"):
        if name in roles:
            call(f"{base}/projects/{project['id']}/users/{user['id']}/roles/{roles[name]}",
                 admin_token, "PUT")
            assigned.append(name)
    credential = rotate_application_credential(base, admin_token, user, password, project, domain)
    output = {"apiVersion": "v1", "kind": "Secret",
              "metadata": {"name": "governance-keystone-application-credential",
                           "namespace": os.environ["DEVELOPMENT_NAMESPACE"]},
              "type": "Opaque", "data": {
                  "auth-url": b64(os.environ["GOVERNANCE_KEYSTONE_SERVICE_URL"]),
                  "application-credential-id": b64(credential["id"]),
                  "application-credential-secret": b64(credential["secret"]),
                  "project-id": b64(project["id"]), "user-id": b64(user["id"]),
                  "roles": b64(",".join(sorted(assigned)))}}
    json.dump(output, sys.stdout, separators=(",", ":"))


if __name__ == "__main__":
    main()
