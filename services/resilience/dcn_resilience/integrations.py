"""Fail-closed, read-only clients for the real development integration boundary."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class IntegrationError(RuntimeError):
    pass


def _request(url: str, method: str = "GET", headers: dict[str, str] | None = None,
             body: dict[str, Any] | None = None, timeout: int = 3) -> tuple[int, dict[str, Any], dict[str, str]]:
    raw = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    request = Request(url, data=raw, method=method, headers={"Accept": "application/json", **(headers or {})})
    if raw is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            payload = json.loads(response.read() or b"{}")
            return response.status, payload, dict(response.headers)
    except HTTPError as exc:
        raise IntegrationError(f"{method} {url} returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise IntegrationError(f"{method} {url} failed: {type(exc).__name__}") from exc


@dataclass
class KeystoneSession:
    auth_url: str
    credential_id: str
    credential_secret: str
    token: str = ""
    catalog: tuple[dict[str, Any], ...] = ()
    project_id: str = ""
    domain_id: str = ""
    user_id: str = ""

    def authenticate(self) -> None:
        body = {"auth": {"identity": {"methods": ["application_credential"], "application_credential": {
            "id": self.credential_id, "secret": self.credential_secret}}}}
        _, payload, headers = _request(urljoin(self.auth_url.rstrip("/") + "/", "v3/auth/tokens"), "POST", body=body)
        self.token = headers.get("X-Subject-Token", "")
        token = payload.get("token", {})
        self.catalog = tuple(token.get("catalog", []))
        self.project_id = token.get("project", {}).get("id", "")
        self.domain_id = token.get("project", {}).get("domain", {}).get("id", "")
        self.user_id = token.get("user", {}).get("id", "")
        if not self.token or not self.project_id or not self.domain_id or not self.user_id:
            raise IntegrationError("Keystone response omitted scoped token or project")

    def endpoint(self, service_type: str, interface: str = "internal") -> str:
        if not self.token:
            self.authenticate()
        for service in self.catalog:
            if service.get("type") == service_type:
                for endpoint in service.get("endpoints", []):
                    if endpoint.get("interface") == interface:
                        return endpoint["url"].replace("$(tenant_id)s", self.project_id)
        raise IntegrationError(f"Keystone catalog has no {service_type}/{interface} endpoint")


@dataclass
class ReadOnlyOpenStackAdapter:
    service: str
    service_type: str
    session: KeystoneSession
    probe_path: str

    def discover(self, project_id: str) -> dict[str, Any]:
        if project_id != self.session.project_id:
            raise IntegrationError("requested project does not match application credential scope")
        endpoint = self.session.endpoint(self.service_type)
        path = self.probe_path.format(project_id=self.session.project_id)
        status, _, _ = _request(endpoint.rstrip("/") + path, headers={"X-Auth-Token": self.session.token})
        return {"service": self.service, "service_type": self.service_type, "installed": True,
                "read_only": True, "http_status": status, "project_id": project_id}

    def observe(self, resource_id: str) -> dict[str, Any]:
        raise IntegrationError("resource observation requires an explicitly typed project-scoped path")

    def execute(self, action: str, resource_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        raise IntegrationError(f"destructive action fenced: {self.service}.{action}")

    def compensate(self, action: str, resource_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        raise IntegrationError(f"compensation fenced: {self.service}.{action}")


SERVICE_PROBES = {
    "cinder": ("volumev3", "/{project_id}/volumes/detail?limit=1"),
    "glance": ("image", "/v2/images?limit=1"),
    "manila": ("sharev2", "/{project_id}/shares/detail?limit=1"),
    "rgw": ("object-store", "/"),
    "nova": ("compute", "/servers/detail?limit=1"),
    "neutron": ("network", "/v2.0/networks?limit=1"),
    "octavia": ("load-balancer", "/v2/lbaas/loadbalancers?limit=1"),
    "designate": ("dns", "/v2/zones?limit=1"),
    "masakari": ("instance-ha", "/segments?limit=1"),
}


def real_catalog(session: KeystoneSession) -> dict[str, ReadOnlyOpenStackAdapter]:
    return {name: ReadOnlyOpenStackAdapter(name, kind, session, path)
            for name, (kind, path) in SERVICE_PROBES.items()}


@dataclass
class OPAClient:
    url: str

    def decide(self, identity: dict[str, Any], authorization_class: str,
               resource: dict[str, Any]) -> dict[str, Any]:
        _, payload, _ = _request(self.url.rstrip("/") + "/v1/data/vpc/authz/decision", "POST",
                                 body={"input": {"subject": identity, "context": {
                                     "authorization_class": authorization_class,
                                     "resource": resource}}})
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("allow") is not True:
            raise IntegrationError("OPA denied or omitted an explicit allow decision")
        return {"allow": True, "policy": result.get("policy"),
                "policy_version": result.get("policy_version")}


def integration_readiness(config) -> dict[str, Any]:
    session = KeystoneSession(config.integration["KEYSTONE_AUTH_URL"],
                              config.integration["KEYSTONE_APPLICATION_CREDENTIAL_ID"],
                              config.integration["KEYSTONE_APPLICATION_CREDENTIAL_SECRET"])
    result: dict[str, Any] = {"mode": config.mode, "destructive_actions": "fenced", "services": {}}
    try:
        session.authenticate()
        result["project_id"] = session.project_id
        for name, adapter in real_catalog(session).items():
            try:
                result["services"][name] = adapter.discover(session.project_id)
            except IntegrationError as exc:
                result["services"][name] = {"installed": False, "reason": str(exc)}
        for key in ("TRACK_A_URL", "TRACK_B_URL"):
            try:
                status, _, _ = _request(config.integration[key].rstrip("/") + "/healthz")
                result[key.lower()] = {"reachable": status == 200, "contract_write": "canonical-v1alpha1"}
            except IntegrationError as exc:
                result[key.lower()] = {"reachable": False, "reason": str(exc)}
    except IntegrationError as exc:
        result["keystone"] = {"reachable": False, "reason": str(exc)}
    try:
        status, _, _ = _request(config.integration["OPA_URL"].rstrip("/") + "/health")
        result["opa"] = {"reachable": status == 200, "authorization": "fail-closed"}
    except IntegrationError as exc:
        result["opa"] = {"reachable": False, "reason": str(exc), "authorization": "fail-closed"}
    blockers = [name for name, value in result["services"].items() if not value.get("installed")]
    blockers += [name for name in ("track_a_url", "track_b_url")
                 if not result.get(name, {}).get("reachable")]
    result["ready"] = not blockers
    result["blockers"] = blockers
    return result
