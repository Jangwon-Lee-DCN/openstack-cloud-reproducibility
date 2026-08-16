import base64
import hashlib
import hmac
import json
import time

from .errors import CoreError, require


class IdentityVerifier:
    """Authenticate identity asserted by a trusted Keystone/OPA proxy boundary."""

    def __init__(self, mode, assertion_key=None, max_age_seconds=60):
        require(mode in {"development", "signed-proxy"}, 500, "AUTH_MODE_INVALID", "authentication mode is invalid")
        if mode == "signed-proxy":
            require(assertion_key and len(assertion_key) >= 32, 500, "AUTH_KEY_WEAK", "proxy assertion key must be at least 32 bytes")
        self.mode, self.key, self.max_age = mode, assertion_key, max_age_seconds

    @staticmethod
    def sign(key, claims):
        body = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()).rstrip(b"=")
        signature = base64.urlsafe_b64encode(hmac.new(key, body, hashlib.sha256).digest()).rstrip(b"=")
        return (body + b"." + signature).decode()

    def verify(self, headers):
        if self.mode == "development":
            project, user = headers.get("X-Project-Id"), headers.get("X-User-Id")
            require(project and user, 401, "IDENTITY_REQUIRED", "development identity headers are required")
            return {"project_id": project, "user_id": user, "roles": [x.strip() for x in headers.get("X-Roles", "").split(",") if x.strip()]}
        token = headers.get("X-DCN-Identity-Assertion")
        require(token, 401, "SIGNED_IDENTITY_REQUIRED", "signed proxy identity assertion is required")
        try:
            body, signature = token.encode().split(b".", 1)
            expected = base64.urlsafe_b64encode(hmac.new(self.key, body, hashlib.sha256).digest()).rstrip(b"=")
            require(hmac.compare_digest(signature, expected), 401, "IDENTITY_SIGNATURE_INVALID", "identity assertion signature is invalid")
            claims = json.loads(base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4)))
        except CoreError:
            raise
        except Exception as exc:
            raise CoreError(401, "IDENTITY_ASSERTION_INVALID", "identity assertion is invalid") from exc
        require(claims.get("project_id") and claims.get("user_id"), 401, "IDENTITY_CLAIMS_MISSING", "identity claims are incomplete")
        require(abs(time.time() - float(claims.get("issued_at", 0))) <= self.max_age, 401, "IDENTITY_ASSERTION_EXPIRED", "identity assertion expired")
        require(claims.get("opa_decision") == "allow" and claims.get("opa_decision_id"), 403, "OPA_POLICY_DENIED", "OPA did not authorize the request")
        return claims


class SignedEventVerifier:
    def __init__(self, key, max_age_seconds=300):
        require(key and len(key) >= 32, 500, "EVENT_KEY_WEAK", "event signing key must be at least 32 bytes")
        self.key, self.max_age = key, max_age_seconds

    def sign(self, body, timestamp):
        return hmac.new(self.key, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()

    def verify(self, body, timestamp, signature):
        try: issued = int(timestamp)
        except (TypeError, ValueError) as exc: raise CoreError(401, "EVENT_TIMESTAMP_INVALID", "event timestamp is invalid") from exc
        require(abs(int(time.time()) - issued) <= self.max_age, 401, "EVENT_EXPIRED", "event is outside the accepted time window")
        require(hmac.compare_digest(self.sign(body, timestamp), signature or ""), 401, "EVENT_SIGNATURE_INVALID", "event signature is invalid")
