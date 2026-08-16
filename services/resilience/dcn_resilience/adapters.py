"""Explicit OpenStack ports and deterministic development adapters.

Production clients must implement these narrow protocols. The fake catalog is
stateful enough to exercise reconciliation without credentials or network I/O.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol


class OpenStackAdapter(Protocol):
    service: str

    def discover(self, project_id: str) -> dict[str, Any]: ...
    def execute(self, action: str, resource_id: str, parameters: dict[str, Any]) -> dict[str, Any]: ...
    def observe(self, resource_id: str) -> dict[str, Any]: ...
    def compensate(self, action: str, resource_id: str, evidence: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class DeterministicServiceFake:
    service: str
    capabilities: set[str]
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    def discover(self, project_id: str) -> dict[str, Any]:
        return {"service": self.service, "project_id": project_id, "capabilities": sorted(self.capabilities)}

    def execute(self, action: str, resource_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if action not in self.capabilities:
            raise ValueError(f"{self.service} does not support {action}")
        call = f"{self.service}.{action}:{resource_id}"
        self.calls.append(call)
        if action in self.failures:
            raise RuntimeError(f"injected {self.service} failure: {action}")
        generation = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
        value = {"id": resource_id, "state": "available", "generation": f"sha256:{generation}", **parameters}
        self.resources[resource_id] = value
        return {"service": self.service, "action": action, "resource_id": resource_id,
                "generation": value["generation"]}

    def observe(self, resource_id: str) -> dict[str, Any]:
        return dict(self.resources.get(resource_id, {"id": resource_id, "state": "missing"}))

    def compensate(self, action: str, resource_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(f"{self.service}.compensate-{action}:{resource_id}")
        self.resources.pop(resource_id, None)
        return {"service": self.service, "compensated": action, "resource_id": resource_id,
                "evidence_generation": evidence.get("generation")}


def development_catalog() -> dict[str, DeterministicServiceFake]:
    return {
        "cinder": DeterministicServiceFake("cinder", {"backup", "snapshot", "restore", "delete"}),
        "glance": DeterministicServiceFake("glance", {"stage", "promote", "deprecate", "deactivate"}),
        "manila": DeterministicServiceFake("manila", {"snapshot", "restore", "delete"}),
        "rgw": DeterministicServiceFake("rgw", {"export", "sample", "delete"}),
        "nova": DeterministicServiceFake("nova", {"boot", "live-migrate", "cold-migrate", "evacuate", "delete"}),
        "neutron": DeterministicServiceFake("neutron", {"inspect", "probe", "restore-port", "switch-fip"}),
        "octavia": DeterministicServiceFake("octavia", {"inspect", "attach-member", "detach-member"}),
        "designate": DeterministicServiceFake("designate", {"inspect", "switch-record", "restore-record"}),
        "masakari": DeterministicServiceFake("masakari", {"inspect", "lock", "unlock", "evacuate"}),
    }
