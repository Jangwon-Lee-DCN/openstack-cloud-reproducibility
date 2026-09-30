import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API_URL = os.getenv(
    "FLAVOR_CATALOG_API_URL",
    "http://flavor-catalog.openstack.svc.cluster.local:8080",
).rstrip("/")

_RETRY = Retry(
    total=2,
    connect=2,
    read=2,
    status=2,
    backoff_factor=0.25,
    status_forcelist=(429, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,
)
_SESSION = requests.Session()
_SESSION.mount("http://", HTTPAdapter(max_retries=_RETRY))
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


def _token_id(user):
    token = getattr(user, "token", None)
    return getattr(token, "id", token) if token else None


def get_catalog(user):
    token = _token_id(user)
    if not token:
        raise ValueError("project-scoped user token is unavailable")
    response = _SESSION.get(
        f"{API_URL}/v1/flavors",
        headers={"X-Auth-Token": str(token)},
        timeout=(3.05, 10),
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
