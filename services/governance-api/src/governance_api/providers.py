from __future__ import annotations

import json
import os
import socket
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    configured: bool
    reachable: bool
    detail: str


class OpenStackClient:
    """Small, secret-safe OpenStack adapter used by all provider implementations."""

    def __init__(self, endpoint: str, token: str = "", timeout: float = 5):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, path: str, *, method="GET", body=None, extra_headers=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-Auth-Token"] = self.token
        headers.update(extra_headers or {})
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.endpoint}{path}", data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout, context=ssl.create_default_context()) as response:
                payload = response.read()
                if not payload:
                    return response.status, {}
                try:
                    return response.status, json.loads(payload)
                except json.JSONDecodeError:
                    return response.status, {}
        except HTTPError as exc:
            # Status is useful; response bodies can contain deployment detail and are not exposed.
            raise ProviderError(f"provider returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError("provider is unreachable") from exc


class KeystoneIdentity:
    def __init__(self, endpoint: str, timeout: float = 5):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def validate(self, token: str, project_id: str) -> dict:
        if not token:
            raise ProviderError("Keystone token is required")
        _, document = OpenStackClient(self.endpoint, token, self.timeout).request(
            "/v3/auth/tokens", extra_headers={"X-Subject-Token": token})
        identity = document.get("token", {})
        scoped_project = identity.get("project", {}).get("id")
        if scoped_project != project_id:
            raise ProviderError("token is not authorized for requested project")
        return {"project_id": project_id, "domain_id": identity.get("project", {}).get("domain", {}).get("id"),
                "user_id": identity.get("user", {}).get("id"),
                "roles": [role.get("name") for role in identity.get("roles", []) if role.get("name")]}


class OpaAuthorizer:
    def __init__(self, endpoint: str, decision_path: str, timeout: float = 5):
        self.client = OpenStackClient(endpoint, timeout=timeout)
        self.decision_path = "/v1/data/" + decision_path.strip("/")

    def authorize(self, policy_input: dict) -> bool:
        _, result = self.client.request(self.decision_path, method="POST", body={"input": policy_input})
        decision = result.get("result")
        if isinstance(decision, dict):
            decision = decision.get("allow")
        return decision is True


def tcp_probe(host: str, port: int, timeout=3) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


class ProviderRegistry:
    HTTP_PROVIDERS = ("keystone", "opa", "gnocchi", "barbican", "designate", "octavia",
                      "nova", "cinder", "neutron", "glance", "cloudkitty", "audit")
    REQUIRED = ("keystone", "opa", "gnocchi", "barbican", "designate", "octavia",
                "nova", "cinder", "neutron", "glance",
                "postgresql", "rabbitmq")

    def __init__(self, environ=None):
        self.environ = environ or os.environ

    def statuses(self) -> list[ProviderStatus]:
        statuses = []
        for name in self.HTTP_PROVIDERS:
            endpoint = self.environ.get(f"GOVERNANCE_{name.upper()}_URL", "")
            if not endpoint:
                statuses.append(ProviderStatus(name, False, False, "endpoint_missing"))
                continue
            try:
                # An authenticated endpoint returning 401/403 proves reachability too.
                OpenStackClient(endpoint).request("/" if name == "opa" else "")
                statuses.append(ProviderStatus(name, True, True, "reachable"))
            except ProviderError as exc:
                detail = str(exc)
                reachable = detail.startswith("provider returned HTTP ")
                statuses.append(ProviderStatus(name, True, reachable, "auth_required" if reachable else detail))
        for name, default_port in (("postgresql", 5432), ("rabbitmq", 5672)):
            host = self.environ.get(f"GOVERNANCE_{name.upper()}_HOST", "")
            port = int(self.environ.get(f"GOVERNANCE_{name.upper()}_PORT", default_port))
            if not host:
                statuses.append(ProviderStatus(name, False, False, "endpoint_missing"))
                continue
            try:
                tcp_probe(host, port)
                statuses.append(ProviderStatus(name, True, True, "reachable"))
            except OSError:
                statuses.append(ProviderStatus(name, True, False, "provider is unreachable"))
        return statuses

    def ready(self) -> bool:
        statuses = {item.name: item for item in self.statuses()}
        return all(statuses[name].configured and statuses[name].reachable for name in self.REQUIRED)
