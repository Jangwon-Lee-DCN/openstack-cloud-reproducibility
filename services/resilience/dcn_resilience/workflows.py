"""Safety-focused Track C workflow definitions.

Adapters return evidence rather than leaking raw infrastructure objects. Real
OpenStack adapters replace this deterministic development adapter at integration.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass, field
from typing import Any, Callable


class PolicyViolation(RuntimeError):
    pass


@dataclass
class DevelopmentAdapter:
    failures: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)

    def call(self, action: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(action)
        if action in self.failures:
            raise RuntimeError(f"injected failure: {action}")
        digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        return {"action": action, "evidence_digest": f"sha256:{digest}", "adapter": "development/v1"}


def _backup(request: dict[str, Any], adapter: DevelopmentAdapter):
    if request.get("consistency") == "application" and not request.get("guest_agent", False):
        raise PolicyViolation("application consistency requires a working guest agent")
    steps = []
    if request.get("consistency") in {"filesystem", "application"}:
        steps.append(("freeze", lambda: adapter.call("backup.freeze", request)))
    steps.extend([
        ("capture", lambda: adapter.call("backup.capture", request)),
        ("checksum", lambda: adapter.call("backup.checksum", request)),
        ("restore-isolated", lambda: adapter.call("backup.restore-isolated", request)),
        ("probe", lambda: adapter.call("backup.probe", request)),
        ("cleanup", lambda: adapter.call("backup.cleanup", request)),
    ])
    return steps


def _dr(request: dict[str, Any], adapter: DevelopmentAdapter):
    if request.get("mode", "drill") != "drill" and not request.get("approved", False):
        raise PolicyViolation("live failover/failback requires explicit approval")
    if not request.get("fencing_verified", False):
        raise PolicyViolation("source fencing evidence is required before writable recovery")
    return [(name, lambda name=name: adapter.call(f"dr.{name}", request)) for name in (
        "validate", "fence-source", "recover-storage", "recreate-compute", "restore-network",
        "health-check", "switch-services")]


def _network(request: dict[str, Any], adapter: DevelopmentAdapter):
    if request.get("source_project_id") != request.get("project_id"):
        raise PolicyViolation("cross-project source is forbidden")
    address = request.get("destination", "")
    try:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast:
            raise PolicyViolation("destination address class is forbidden")
    except ValueError:
        if not address or len(address) > 253:
            raise PolicyViolation("invalid destination")
    if int(request.get("packet_count", 3)) > 3 or int(request.get("timeout_seconds", 10)) > 10:
        raise PolicyViolation("probe limits exceeded")
    return [("analyze", lambda: adapter.call("network.analyze-redacted", request)),
            ("probe", lambda: adapter.call("network.probe-limited", request)),
            ("compare", lambda: adapter.call("network.compare", request))]


def maintenance_eligibility(instance: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = []
    for key in ("pci_passthrough", "numa_pinned", "hugepages", "local_disk"):
        if instance.get(key):
            reasons.append(key)
    return ("blocked", reasons) if reasons else ("eligible", [])


def _maintenance(request: dict[str, Any], adapter: DevelopmentAdapter):
    max_unavailable = int(request.get("max_unavailable", 1))
    if max_unavailable < 1:
        raise PolicyViolation("max_unavailable must be at least one")
    blocked = []
    for instance in request.get("instances", []):
        status, reasons = maintenance_eligibility(instance)
        if status == "blocked":
            blocked.append({"instance_id": instance.get("id"), "reason_codes": reasons})
    if blocked and request.get("strategy", "live-migrate") == "live-migrate":
        raise PolicyViolation(f"unsafe live migration blocked: {blocked}")
    return [(name, lambda name=name: adapter.call(f"maintenance.{name}", request)) for name in (
        "impact", "capacity", "disable-scheduling", "migrate-bounded", "verify-dataplane", "health-gate", "enable-scheduling")]


def _image(request: dict[str, Any], adapter: DevelopmentAdapter):
    required = ("source_digest", "artifact_digest", "signature_ref", "sbom_ref", "provenance_ref")
    missing = [key for key in required if not request.get(key)]
    if missing:
        raise PolicyViolation(f"promotion evidence missing: {missing}")
    if not all(str(request[key]).startswith("sha256:") for key in ("source_digest", "artifact_digest")):
        raise PolicyViolation("source and artifact digest must be sha256")
    if request.get("critical_vulnerabilities", 0) > 0:
        raise PolicyViolation("critical vulnerability policy exceeded")
    if not request.get("signature_verified", False) or not request.get("test_boot_passed", False):
        raise PolicyViolation("verified signature and test boot are mandatory")
    if request.get("owner_project_id") != request.get("platform_owner_project_id"):
        raise PolicyViolation("only the configured platform owner may promote official images")
    if request.get("image_class") != "platform":
        raise PolicyViolation("official promotion requires dcn_image_class=platform")
    return [(name, lambda name=name: adapter.call(f"image.{name}", request)) for name in (
        "verify-manifest", "verify-sbom", "verify-signature", "verify-test-results", "promote-metadata")]


WORKFLOWS: dict[str, Callable[[dict[str, Any], DevelopmentAdapter], list[tuple[str, Callable[[], dict[str, Any]]]]]] = {
    "backup-run": _backup,
    "dr-execution": _dr,
    "network-diagnostic": _network,
    "maintenance": _maintenance,
    "image-promotion": _image,
}


def compensation(kind: str, adapter: DevelopmentAdapter, request: dict[str, Any], completed: set[str]) -> list[dict[str, Any]]:
    evidence = []
    if kind == "backup-run":
        if "freeze" in completed:
            evidence.append(adapter.call("backup.thaw", request))
        if "restore-isolated" in completed and "cleanup" not in completed:
            evidence.append(adapter.call("backup.cleanup", request))
    if kind == "maintenance" and "disable-scheduling" in completed and "enable-scheduling" not in completed:
        evidence.append(adapter.call("maintenance.restore-scheduler-state", request))
    return evidence
