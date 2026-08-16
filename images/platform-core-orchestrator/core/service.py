import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

from .errors import CoreError, require
from .store import Store


TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
RESTORE_CAPABILITIES = {
    "instance": "FULL",
    "launch_template": "METADATA_ONLY",
    "auto_scaling_group": "METADATA_ONLY",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def fingerprint(payload):
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class CoreService:
    def __init__(self, store: Store, signing_key: bytes, approval_ttl=300):
        require(len(signing_key) >= 32, 500, "CONFIG_SIGNING_KEY_WEAK", "approval signing key must be at least 32 bytes")
        self.store = store
        self.signing_key = signing_key
        self.approval_ttl = approval_ttl

    def _owned(self, db, table, resource_id, project_id):
        row = db.execute(f"SELECT * FROM {table} WHERE id=? AND project_id=?", (resource_id, project_id)).fetchone()
        require(row, 404, "RESOURCE_NOT_FOUND", "resource was not found")
        return Store.row(row)

    def create_operation(self, project_id, region_id, action, target_type, payload, key, target_id=None):
        require(key and len(key) <= 255, 400, "IDEMPOTENCY_KEY_REQUIRED", "a bounded Idempotency-Key is required")
        fp, created, operation_id, correlation_id, timestamp = fingerprint(payload), False, str(uuid.uuid4()), str(uuid.uuid4()), now()
        with self.store.tx() as db:
            existing = db.execute("SELECT * FROM operations WHERE project_id=? AND idempotency_key=?", (project_id, key)).fetchone()
            if existing:
                existing = Store.row(existing)
                require(existing["fingerprint"] == fp, 409, "IDEMPOTENCY_KEY_REUSED", "the key was already used with another request")
                return existing, created
            db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                operation_id, project_id, region_id, action, target_type, target_id, fp, key,
                "REQUESTED", 0, None, None, correlation_id, timestamp, timestamp))
            event = {"state": "REQUESTED", "correlation_id": correlation_id}
            db.execute("INSERT INTO operation_events(operation_id,event_type,payload_json,created_at) VALUES(?,?,?,?)", (operation_id, "operation.requested", canonical(event), timestamp))
            db.execute("INSERT INTO outbox(topic,aggregate_id,payload_json,created_at) VALUES(?,?,?,?)", ("operation.requested.v1", operation_id, canonical(event), timestamp))
            created = True
        return self.get_operation(project_id, operation_id), created

    def get_operation(self, project_id, operation_id):
        with self.store.tx() as db:
            return self._owned(db, "operations", operation_id, project_id)

    def list_operations(self, project_id, state=None):
        query, args = "SELECT * FROM operations WHERE project_id=?", [project_id]
        if state:
            query += " AND state=?"; args.append(state)
        with self.store.tx() as db:
            return [Store.row(x) for x in db.execute(query + " ORDER BY created_at DESC", args)]

    def operation_events(self, project_id, operation_id):
        self.get_operation(project_id, operation_id)
        with self.store.tx() as db:
            return [Store.row(x) for x in db.execute("SELECT * FROM operation_events WHERE operation_id=? ORDER BY id", (operation_id,))]

    def cancel_operation(self, project_id, operation_id):
        with self.store.tx() as db:
            op = self._owned(db, "operations", operation_id, project_id)
            require(op["state"] not in TERMINAL, 409, "OPERATION_NOT_CANCELLABLE", "terminal operations cannot be cancelled")
            timestamp = now()
            db.execute("UPDATE operations SET state='CANCELLED',updated_at=? WHERE id=?", (timestamp, operation_id))
            db.execute("INSERT INTO outbox(topic,aggregate_id,payload_json,created_at) VALUES(?,?,?,?)", ("operation.cancelled.v1", operation_id, "{}", timestamp))
        return self.get_operation(project_id, operation_id)

    def retry_operation(self, project_id, operation_id, key):
        old = self.get_operation(project_id, operation_id)
        require(old["state"] == "FAILED", 409, "OPERATION_NOT_RETRYABLE", "only failed operations may be retried")
        return self.create_operation(project_id, old["region_id"], old["action"] + ".retry", old["target_type"], {"retry_of": operation_id}, key, old["target_id"])

    def _token(self, claims):
        body = base64.urlsafe_b64encode(canonical(claims).encode()).rstrip(b"=")
        sig = base64.urlsafe_b64encode(hmac.new(self.signing_key, body, hashlib.sha256).digest()).rstrip(b"=")
        return (body + b"." + sig).decode()

    def verify_approval(self, token, project_id, payload):
        try:
            body64, sig64 = token.encode().split(b".", 1)
            expected = base64.urlsafe_b64encode(hmac.new(self.signing_key, body64, hashlib.sha256).digest()).rstrip(b"=")
            require(hmac.compare_digest(sig64, expected), 409, "APPROVAL_TOKEN_INVALID", "approval token is invalid")
            claims = json.loads(base64.urlsafe_b64decode(body64 + b"=" * (-len(body64) % 4)))
        except CoreError:
            raise
        except Exception as exc:
            raise CoreError(409, "APPROVAL_TOKEN_INVALID", "approval token is invalid") from exc
        require(claims["project_id"] == project_id, 403, "PROJECT_SCOPE_MISMATCH", "approval belongs to another project")
        require(claims["fingerprint"] == fingerprint(payload), 409, "APPROVAL_PAYLOAD_CHANGED", "payload changed after preflight")
        require(datetime.fromisoformat(claims["expires_at"]) > datetime.now(timezone.utc), 409, "APPROVAL_TOKEN_EXPIRED", "approval token expired")
        return claims

    def preflight(self, project_id, kind, payload):
        checks = []
        def check(name, passed, code):
            checks.append({"name": name, "result": "PASS" if passed else "FAIL", "code": code})
        check("request.region", bool(payload.get("region_id")), "REGION_REQUIRED")
        check("request.subnet", bool(payload.get("subnet_id") or payload.get("subnet_ids")), "SUBNET_REQUIRED")
        if kind == "auto-scaling-group":
            low, desired, high = payload.get("min_size", -1), payload.get("desired_capacity", -1), payload.get("max_size", -1)
            check("capacity.bounds", 0 <= low <= desired <= high, "CAPACITY_BOUNDS_INVALID")
        decision = "FAIL" if any(x["result"] == "FAIL" for x in checks) else "PASS"
        ident, expires = str(uuid.uuid4()), datetime.now(timezone.utc) + timedelta(seconds=self.approval_ttl)
        claims = {"preflight_id": ident, "project_id": project_id, "fingerprint": fingerprint(payload), "expires_at": expires.isoformat()}
        result = {"id": ident, "decision": decision, "checks": checks, "resolved": {"region_id": payload.get("region_id"), "subnet_ids": payload.get("subnet_ids") or [payload.get("subnet_id")]}, "expires_at": expires.isoformat(), "approval_token": self._token(claims) if decision == "PASS" else None}
        with self.store.tx() as db:
            db.execute("INSERT INTO preflights VALUES(?,?,?,?,?,?,?)", (ident, project_id, kind, claims["fingerprint"], decision, canonical(result), expires.isoformat()))
        return result

    def create_template(self, project_id, user_id, body):
        require(body.get("name"), 400, "TEMPLATE_NAME_REQUIRED", "template name is required")
        spec = body.get("version") or {}
        for field in ("image_id", "flavor_id", "subnet_id"):
            require(spec.get(field), 400, "TEMPLATE_REFERENCE_REQUIRED", f"{field} is required")
        require(not spec.get("user_data"), 400, "PLAINTEXT_SECRET_FORBIDDEN", "use user_data_ref instead of plaintext user data")
        ident, timestamp, checksum = str(uuid.uuid4()), now(), fingerprint(spec)
        with self.store.tx() as db:
            try:
                db.execute("INSERT INTO launch_templates VALUES(?,?,?,?,?,?,?)", (ident, project_id, body["name"], body.get("description", ""), 1, int(body.get("deletion_protected", False)), timestamp))
            except Exception as exc:
                raise CoreError(409, "TEMPLATE_NAME_CONFLICT", "template name already exists") from exc
            db.execute("INSERT INTO launch_template_versions VALUES(?,?,?,?,?,?)", (ident, 1, canonical(spec), checksum, user_id, timestamp))
        return self.get_template(project_id, ident)

    def get_template(self, project_id, ident):
        with self.store.tx() as db:
            template = self._owned(db, "launch_templates", ident, project_id)
            template["versions"] = [Store.row(x) for x in db.execute("SELECT * FROM launch_template_versions WHERE template_id=? ORDER BY version", (ident,))]
            return template

    def add_template_version(self, project_id, user_id, ident, spec):
        self.get_template(project_id, ident)
        require(not spec.get("user_data"), 400, "PLAINTEXT_SECRET_FORBIDDEN", "use user_data_ref instead")
        with self.store.tx() as db:
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM launch_template_versions WHERE template_id=?", (ident,)).fetchone()[0]
            db.execute("INSERT INTO launch_template_versions VALUES(?,?,?,?,?,?)", (ident, version, canonical(spec), fingerprint(spec), user_id, now()))
        return self.get_template(project_id, ident)

    def set_default_version(self, project_id, ident, version):
        with self.store.tx() as db:
            self._owned(db, "launch_templates", ident, project_id)
            require(db.execute("SELECT 1 FROM launch_template_versions WHERE template_id=? AND version=?", (ident, version)).fetchone(), 404, "TEMPLATE_VERSION_NOT_FOUND", "template version was not found")
            db.execute("UPDATE launch_templates SET default_version=? WHERE id=?", (version, ident))
        return self.get_template(project_id, ident)

    def create_asg(self, project_id, body):
        low, desired, high = body.get("min_size"), body.get("desired_capacity"), body.get("max_size")
        require(all(isinstance(x, int) for x in (low, desired, high)) and 0 <= low <= desired <= high, 400, "CAPACITY_BOUNDS_INVALID", "require 0 <= min <= desired <= max")
        template = self.get_template(project_id, body["launch_template_id"])
        version = body.get("launch_template_version") or template["default_version"]
        require(any(x["version"] == version for x in template["versions"]), 404, "TEMPLATE_VERSION_NOT_FOUND", "template version was not found")
        ident, timestamp = str(uuid.uuid4()), now()
        with self.store.tx() as db:
            db.execute("INSERT INTO auto_scaling_groups VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (ident, project_id, body["region_id"], template["id"], version, low, desired, high, canonical(body.get("subnet_ids", [])), body.get("cooldown_seconds", 300), "ACTIVE", int(body.get("deletion_protected", False)), None, timestamp))
        return self.get_asg(project_id, ident)

    def get_asg(self, project_id, ident):
        with self.store.tx() as db:
            return self._owned(db, "auto_scaling_groups", ident, project_id)

    def scaling_event(self, project_id, ident, event_id, adjustment):
        require(isinstance(adjustment, int) and adjustment != 0, 400, "SCALING_ADJUSTMENT_INVALID", "adjustment must be a non-zero integer")
        with self.store.tx() as db:
            group = self._owned(db, "auto_scaling_groups", ident, project_id)
            existing = db.execute("SELECT * FROM scaling_events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                event = Store.row(existing)
                return {**event, "accepted": bool(event["accepted"]), "desired_capacity": group["desired"]}
            desired = max(group["min_size"], min(group["max_size"], group["desired"] + adjustment))
            accepted, reason = desired != group["desired"], "accepted" if desired != group["desired"] else "capacity-bound"
            timestamp = now()
            db.execute("INSERT INTO scaling_events VALUES(?,?,?,?,?,?)", (event_id, ident, adjustment, int(accepted), reason, timestamp))
            if accepted:
                db.execute("UPDATE auto_scaling_groups SET desired=?,state='SCALING',last_scaled_at=? WHERE id=?", (desired, timestamp, ident))
        return {"event_id": event_id, "group_id": ident, "accepted": accepted, "reason": reason, "desired_capacity": desired}

    def set_protection(self, project_id, user_id, resource_type, resource_id, protected, reason=None):
        timestamp = now()
        with self.store.tx() as db:
            db.execute("INSERT INTO resource_protection VALUES(?,?,?,?,?,?,?) ON CONFLICT(project_id,resource_type,resource_id) DO UPDATE SET protected=excluded.protected,reason=excluded.reason,updated_by=excluded.updated_by,updated_at=excluded.updated_at", (project_id, resource_type, resource_id, int(protected), reason, user_id, timestamp))
            db.execute("INSERT INTO outbox(topic,aggregate_id,payload_json,created_at) VALUES(?,?,?,?)", ("resource.protection.changed.v1", resource_id, canonical({"resource_type": resource_type, "protected": protected}), timestamp))
        return {"resource_type": resource_type, "resource_id": resource_id, "deletion_protected": protected, "reason": reason}

    def recycle(self, project_id, user_id, resource_type, resource_id, retention_days=7):
        with self.store.tx() as db:
            protected = db.execute("SELECT protected FROM resource_protection WHERE project_id=? AND resource_type=? AND resource_id=?", (project_id, resource_type, resource_id)).fetchone()
            require(not protected or not protected[0], 409, "RESOURCE_PROTECTED", "deletion protection is enabled")
            timestamp, ident = datetime.now(timezone.utc), str(uuid.uuid4())
            capability = RESTORE_CAPABILITIES.get(resource_type, "NONE")
            db.execute("INSERT INTO recycle_bin VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ident, project_id, resource_type, resource_id, "{}", user_id, timestamp.isoformat(), (timestamp + timedelta(days=retention_days)).isoformat(), capability, "{}", "RETAINED"))
            db.execute("INSERT INTO outbox(topic,aggregate_id,payload_json,created_at) VALUES(?,?,?,?)", ("recycle-bin.retained.v1", ident, canonical({"resource_type": resource_type, "resource_id": resource_id}), timestamp.isoformat()))
        return self.get_recycle(project_id, ident)

    def get_recycle(self, project_id, ident):
        with self.store.tx() as db:
            return self._owned(db, "recycle_bin", ident, project_id)

    def list_recycle(self, project_id):
        with self.store.tx() as db:
            return [Store.row(x) for x in db.execute("SELECT * FROM recycle_bin WHERE project_id=? ORDER BY deleted_at DESC", (project_id,))]

    def restore(self, project_id, ident):
        with self.store.tx() as db:
            entry = self._owned(db, "recycle_bin", ident, project_id)
            require(entry["state"] == "RETAINED", 409, "RECYCLE_STATE_INVALID", "entry is not retained")
            require(entry["restore_capability"] != "NONE", 409, "RESTORE_NOT_SUPPORTED", "resource cannot be restored")
            require(datetime.fromisoformat(entry["purge_after"]) > datetime.now(timezone.utc), 409, "RETENTION_EXPIRED", "retention period expired")
            db.execute("UPDATE recycle_bin SET state='RESTORED' WHERE id=?", (ident,))
        return self.get_recycle(project_id, ident)
