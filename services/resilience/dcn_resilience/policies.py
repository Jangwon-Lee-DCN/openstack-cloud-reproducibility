"""Pure policy functions shared by controllers and contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def retention_decision(generations: list[dict[str, Any]], keep_last: int) -> dict[str, list[str]]:
    """Return stable keep/expire sets without deleting protected generations."""
    ordered = sorted(generations, key=lambda item: item["completed_at"], reverse=True)
    mandatory = {item["id"] for item in ordered
                 if item.get("legal_hold") or item.get("restore_reference") or item.get("state") == "running"}
    successful = [item["id"] for item in ordered if item.get("state") == "succeeded"]
    mandatory.update(successful[:max(keep_last, 1)])  # never remove the latest successful recovery point
    return {
        "keep": [item["id"] for item in ordered if item["id"] in mandatory],
        "expire": [item["id"] for item in ordered if item["id"] not in mandatory and item.get("state") != "running"],
    }


def validate_restore_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    required = {"artifact_checksum", "restored_checksum", "probes", "cleanup_state"}
    missing = required - evidence.keys()
    if missing:
        raise ValueError(f"restore evidence missing {sorted(missing)}")
    checksum_match = evidence["artifact_checksum"] == evidence["restored_checksum"]
    probes_passed = bool(evidence["probes"]) and all(probe.get("result") == "passed" for probe in evidence["probes"])
    cleanup_complete = evidence["cleanup_state"] == "complete"
    return {"restorable": checksum_match and probes_passed, "checksum_match": checksum_match,
            "probes_passed": probes_passed, "cleanup_complete": cleanup_complete,
            "manual_cleanup_required": not cleanup_complete}


def dr_objectives(recovery_point: str, detected_at: str, healthy_at: str,
                  target_rpo_seconds: int, target_rto_seconds: int) -> dict[str, Any]:
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    recovery, detected, healthy = parse(recovery_point), parse(detected_at), parse(healthy_at)
    if recovery > detected or detected > healthy:
        raise ValueError("DR timeline must satisfy recovery_point <= detected_at <= healthy_at")
    if target_rpo_seconds < 0 or target_rto_seconds < 0:
        raise ValueError("RPO and RTO targets cannot be negative")
    rpo = int((detected - recovery).total_seconds())
    rto = int((healthy - detected).total_seconds())
    return {"measured_rpo_seconds": rpo, "measured_rto_seconds": rto,
            "rpo_met": rpo <= target_rpo_seconds, "rto_met": rto <= target_rto_seconds}


def explain_network_path(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Produce user-safe first-failure decisions in packet evaluation order."""
    decisions = []
    checks = (
        ("source-binding", snapshot.get("source_bound", False), "SOURCE_PORT_UNBOUND"),
        ("security-group-egress", snapshot.get("sg_egress", False), "SECURITY_GROUP_EGRESS_DENY"),
        ("network-acl-egress", snapshot.get("nacl_egress", False), "NETWORK_ACL_EGRESS_DENY"),
        ("route", snapshot.get("route_present", False), "NO_ROUTE"),
        ("nat", snapshot.get("nat_ready", True), "NAT_UNAVAILABLE"),
        ("load-balancer", snapshot.get("lb_healthy", True), "LOAD_BALANCER_UNHEALTHY"),
        ("network-acl-ingress", snapshot.get("nacl_ingress", False), "NETWORK_ACL_INGRESS_DENY"),
        ("security-group-ingress", snapshot.get("sg_ingress", False), "SECURITY_GROUP_INGRESS_DENY"),
    )
    verdict, reason = "reachable", None
    for component, allowed, denied_reason in checks:
        decisions.append({"component": component, "decision": "allow" if allowed else "deny"})
        if not allowed:
            verdict, reason = "blocked", denied_reason
            break
    if snapshot.get("declared_reachable") and not snapshot.get("probe_reachable") and verdict == "reachable":
        verdict, reason = "mismatch", "DECLARED_ALLOWED_PROBE_FAILED"
    return {"verdict": verdict, "reason_code": reason, "decisions": decisions,
            "infrastructure": "redacted"}


def maintenance_action(instance: dict[str, Any], planned: bool, masakari_locked: bool) -> dict[str, Any]:
    constraints = []
    if instance.get("pci_passthrough"): constraints.append("PCI_PASSTHROUGH")
    if instance.get("numa_pinned"): constraints.append("NUMA_PINNING")
    if instance.get("hugepages"): constraints.append("HUGEPAGES")
    if instance.get("local_disk"): constraints.append("LOCAL_DISK")
    if instance.get("anti_affinity_target_unavailable"): constraints.append("ANTI_AFFINITY")
    if masakari_locked:
        return {"action": "blocked", "reason_codes": ["MASAKARI_OPERATION_ACTIVE"]}
    if planned and not constraints:
        return {"action": "live-migrate", "reason_codes": []}
    if planned and "LOCAL_DISK" not in constraints:
        return {"action": "cold-migrate", "reason_codes": constraints}
    if not planned and not instance.get("shared_storage", True):
        return {"action": "manual", "reason_codes": constraints + ["NO_SHARED_STORAGE"]}
    return {"action": "evacuate" if not planned else "manual", "reason_codes": constraints}


def image_attestation_gate(image: dict[str, Any], platform_owner: str, revoked_digests: set[str]) -> dict[str, Any]:
    reasons = []
    digest = image.get("artifact_digest", "")
    if image.get("owner_project_id") != platform_owner: reasons.append("UNTRUSTED_OWNER")
    if image.get("image_class") != "platform": reasons.append("INVALID_IMAGE_CLASS")
    if not digest.startswith("sha256:"): reasons.append("INVALID_DIGEST")
    if digest in revoked_digests: reasons.append("REVOKED_DIGEST")
    if not image.get("signature_verified"): reasons.append("SIGNATURE_UNVERIFIED")
    if not image.get("provenance_verified"): reasons.append("PROVENANCE_UNVERIFIED")
    if not image.get("sbom_digest", "").startswith("sha256:"): reasons.append("SBOM_UNVERIFIED")
    if image.get("critical_vulnerabilities", 0): reasons.append("CRITICAL_VULNERABILITY")
    if not image.get("test_boot_passed"): reasons.append("TEST_BOOT_FAILED")
    return {"allowed": not reasons, "reason_codes": reasons,
            "required_glance_status": "active" if not reasons else "deactivated"}
