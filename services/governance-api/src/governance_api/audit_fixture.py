from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import Forbidden, GovernanceError
from .security import RequestContext, safe_projection
from .service import GovernanceService


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class DevelopmentAuditSigner:
    source: str
    key: bytes

    def sign(self, event: dict) -> str:
        return hmac.new(self.key, canonical(event), hashlib.sha256).hexdigest()

    def verify(self, event: dict, signature: str) -> bool:
        return hmac.compare_digest(self.sign(event), signature)


class SignedAuditFixture:
    """Deterministic HMAC fixture; production must replace it with asymmetric signing."""

    def __init__(self, service: GovernanceService, signers: dict[str, DevelopmentAuditSigner]):
        self.service = service
        self.signers = signers

    def ingest(self, ctx: RequestContext, source: str, event: dict, signature: str):
        signer = self.signers.get(source)
        if not signer or not signer.verify(event, signature):
            raise GovernanceError("audit source signature invalid", code="invalid_audit_signature")
        if event.get("project_id") != ctx.project_id and not ctx.system_reader:
            raise Forbidden("audit event is outside the token project scope")
        return self.service.append_audit(
            ctx, action=event["action"], target=safe_projection(event["target"]),
            outcome=event["outcome"], request_id=event["request_id"],
            operation_id=event.get("operation_id"), changes=event.get("changes"),
        )

    def export(self, ctx: RequestContext, signer: DevelopmentAuditSigner) -> tuple[bytes, dict]:
        events = list(reversed(self.service.search_audit(ctx)))
        payload = b"".join(canonical(event) + b"\n" for event in events)
        manifest = {
            "schema": "dcn.audit-export.v1alpha1", "project_id": ctx.project_id,
            "event_count": len(events), "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "last_integrity_hash": events[-1]["integrity_hash"] if events else None,
        }
        manifest["signature"] = signer.sign(manifest)
        return payload, manifest

    @staticmethod
    def verify_export(payload: bytes, manifest: dict, signer: DevelopmentAuditSigner) -> bool:
        unsigned = dict(manifest)
        signature = unsigned.pop("signature", "")
        return (signer.verify(unsigned, signature)
                and hashlib.sha256(payload).hexdigest() == unsigned["payload_sha256"]
                and payload.count(b"\n") == unsigned["event_count"])
