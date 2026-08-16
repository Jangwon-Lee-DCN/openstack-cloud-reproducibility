from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

from .errors import Forbidden, GovernanceError


SENSITIVE_KEYS = frozenset({
    "password", "token", "cookie", "authorization", "private_key", "secret",
    "credential", "user_data", "userdata",
})


@dataclass(frozen=True)
class RequestContext:
    domain_id: str
    project_id: str
    user_id: str
    roles: frozenset[str] = frozenset()

    @property
    def system_reader(self) -> bool:
        return "admin" in self.roles or "system_reader" in self.roles

    def require_project(self, project_id: str) -> None:
        if project_id != self.project_id and not self.system_reader:
            raise Forbidden("resource is outside the token project scope")


def safe_projection(value):
    """Allowlist-shaped recursive redaction; unknown values stay structural."""
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else safe_projection(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [safe_projection(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


def validate_webhook_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise GovernanceError("webhook must be an HTTPS URL without userinfo", code="unsafe_webhook")
    host = parsed.hostname.rstrip(".").lower()
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if address and (address.is_private or address.is_loopback or address.is_link_local):
        raise GovernanceError("webhook destination is not routable", code="unsafe_webhook")
    if host not in allowed_hosts:
        raise GovernanceError("webhook destination is not allowlisted", code="unsafe_webhook")
    return url
