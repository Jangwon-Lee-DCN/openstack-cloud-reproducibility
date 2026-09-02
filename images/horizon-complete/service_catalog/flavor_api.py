import os

import requests


API_URL = os.getenv(
    "FLAVOR_CATALOG_API_URL",
    "http://flavor-catalog.openstack.svc.cluster.local:8080",
).rstrip("/")


def _token_id(user):
    token = getattr(user, "token", None)
    return getattr(token, "id", token) if token else None


def get_catalog(user):
    token = _token_id(user)
    if not token:
        raise ValueError("project-scoped user token is unavailable")
    response = requests.get(
        f"{API_URL}/v1/flavors",
        headers={"X-Auth-Token": str(token)},
        timeout=5,
    )
    response.raise_for_status()
    value = response.json()
    if value.get("schema") != "dcn.ssu.ac.kr/flavor-availability/v2":
        raise ValueError("unexpected Flavor availability schema")
    if not isinstance(value.get("flavors"), list):
        raise ValueError("incomplete Flavor availability response")
    return value


def list_flavors(user):
    return get_catalog(user)["flavors"]
