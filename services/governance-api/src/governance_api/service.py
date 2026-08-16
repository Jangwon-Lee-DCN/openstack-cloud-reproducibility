from __future__ import annotations

import hashlib
import hmac
import re
import base64
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import uuid4

from .errors import Conflict, Forbidden, GovernanceError, NotFound
from .events import resource_changed_event
from .event_ingestion import (decode_cursor, encode_cursor, event_hash, normalize_event,
                              validate_event)
from .operation import FakeOperationClient
from .security import RequestContext, safe_projection, validate_webhook_url
from .store import Store


TAG_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]*(/[a-z0-9][a-z0-9_.-]*)?$")
EVENT_PREFIXES = ("operation.", "quota.", "credential.", "certificate.", "backup.",
                  "resource.health.", "budget.", "security.")


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class GovernanceService:
    def __init__(self, store: Store, operation_client=None, *, webhook_hosts=()):
        self.store = store
        self.operations = operation_client or FakeOperationClient()
        self.webhook_hosts = {host.lower() for host in webhook_hosts}

    def _write(self, ctx, kind, body, *, action, key, request_id):
        if not key:
            raise GovernanceError("Idempotency-Key is required", code="idempotency_key_required")
        created = now()
        record = {
            **safe_projection(body), "id": str(uuid4()), "domain_id": ctx.domain_id,
            "project_id": ctx.project_id, "created_by": ctx.user_id, "created_at": created,
            "updated_at": created, "revision": 1,
        }
        with self.store.transaction() as db:
            cached = db.execute(
                "SELECT response FROM idempotency WHERE project_id=? AND action=? AND key=?",
                (ctx.project_id, action, key),
            ).fetchone()
            if cached:
                return self.store.decode(cached[0])
            operation = self.operations.create(action=action, idempotency_key=key, request_id=request_id,
                                               project_id=ctx.project_id, target_type=kind)
            record["operation_id"] = operation.id
            db.execute("INSERT INTO resources VALUES(?,?,?,?,?,?,?,?)", (
                kind, record["id"], ctx.domain_id, ctx.project_id, 1,
                self.store.encode(record), created, created,
            ))
            db.execute("INSERT INTO idempotency VALUES(?,?,?,?)", (
                ctx.project_id, action, key, self.store.encode(record),
            ))
            event = resource_changed_event(ctx, operation, kind, record["id"], request_id, action)
            db.execute(
                "INSERT INTO outbox(id,project_id,event_type,dedup_key,payload,status,available_at,created_at) "
                "VALUES(?,?,?,?,?,'pending',?,?)",
                (event["event_id"], ctx.project_id, event["event_type"], f"{action}:{key}",
                 self.store.encode(event),
                 created, created),
            )
        self.append_audit(ctx, action=action, target={"type": kind, "id": record["id"]},
                          outcome="success", request_id=request_id, operation_id=operation.id)
        return record

    def list_resources(self, ctx: RequestContext, kind: str, *, project_id=None):
        project_id = project_id or ctx.project_id
        ctx.require_project(project_id)
        rows = self.store.connection.execute(
            "SELECT body FROM resources WHERE kind=? AND project_id=? ORDER BY updated_at DESC,id",
            (kind, project_id),
        )
        return [self.store.decode(row[0]) for row in rows]

    def page_resources(self, ctx: RequestContext, kind: str, *, limit=50, cursor=None):
        if limit < 1 or limit > 200:
            raise GovernanceError("limit must be between 1 and 200")
        offset = 0
        if cursor:
            try:
                offset = int(base64.urlsafe_b64decode(cursor + "===").decode())
            except (ValueError, UnicodeError):
                raise GovernanceError("invalid cursor", code="invalid_cursor")
        items = self.list_resources(ctx, kind)
        page = items[offset:offset + limit]
        next_cursor = None
        if offset + len(page) < len(items):
            next_cursor = base64.urlsafe_b64encode(str(offset + len(page)).encode()).decode().rstrip("=")
        return {"items": page, "next": next_cursor}

    def get_resource(self, ctx, kind, resource_id):
        row = self.store.connection.execute(
            "SELECT project_id,body FROM resources WHERE kind=? AND id=?", (kind, resource_id)).fetchone()
        if not row:
            raise NotFound("resource not found")
        ctx.require_project(row[0])
        return self.store.decode(row[1])

    def update_resource(self, ctx, kind, resource_id, changes, *, expected_revision, key, request_id):
        if not key:
            raise GovernanceError("Idempotency-Key is required", code="idempotency_key_required")
        action = f"{kind}.update"
        cached = self.store.connection.execute(
            "SELECT response FROM idempotency WHERE project_id=? AND action=? AND key=?",
            (ctx.project_id, action, key)).fetchone()
        if cached:
            return self.store.decode(cached[0])
        current = self.get_resource(ctx, kind, resource_id)
        if expected_revision != current["revision"]:
            raise Conflict("resource revision conflict")
        protected = {"id", "domain_id", "project_id", "created_by", "created_at", "operation_id"}
        if protected.intersection(changes):
            raise GovernanceError("immutable resource fields cannot be changed")
        updated = {**current, **safe_projection(changes), "revision": current["revision"] + 1, "updated_at": now()}
        operation = self.operations.create(action=action, idempotency_key=key, request_id=request_id,
                                           project_id=ctx.project_id, target_type=kind,
                                           target_id=resource_id)
        updated["operation_id"] = operation.id
        with self.store.transaction() as db:
            cursor = db.execute(
                "UPDATE resources SET revision=?,body=?,updated_at=? WHERE kind=? AND id=? AND project_id=? AND revision=?",
                (updated["revision"], self.store.encode(updated), updated["updated_at"], kind, resource_id,
                 ctx.project_id, expected_revision))
            if cursor.rowcount != 1:
                raise Conflict("resource revision conflict")
            db.execute("INSERT INTO idempotency VALUES(?,?,?,?)",
                       (ctx.project_id, action, key, self.store.encode(updated)))
        self.append_audit(ctx, action=action, target={"type": kind, "id": resource_id},
                          outcome="success", request_id=request_id, operation_id=operation.id, changes=changes)
        return updated

    def delete_resource(self, ctx, kind, resource_id, *, expected_revision, key, request_id):
        if not key:
            raise GovernanceError("Idempotency-Key is required", code="idempotency_key_required")
        action = f"{kind}.delete"
        cached = self.store.connection.execute(
            "SELECT response FROM idempotency WHERE project_id=? AND action=? AND key=?",
            (ctx.project_id, action, key)).fetchone()
        if cached:
            return self.store.decode(cached[0])
        current = self.get_resource(ctx, kind, resource_id)
        if expected_revision != current["revision"]:
            raise Conflict("resource revision conflict")
        with self.store.transaction() as db:
            db.execute("DELETE FROM resources WHERE kind=? AND id=? AND project_id=? AND revision=?",
                       (kind, resource_id, ctx.project_id, expected_revision))
            response = {"id": resource_id, "deleted": True}
            db.execute("INSERT INTO idempotency VALUES(?,?,?,?)",
                       (ctx.project_id, action, key, self.store.encode(response)))
        self.append_audit(ctx, action=action, target={"type": kind, "id": resource_id},
                          outcome="success", request_id=request_id)
        return response

    # Notifications
    def create_subscription(self, ctx, body, *, key, request_id):
        channels = body.get("channels", [])
        for channel in channels:
            if channel.get("type") == "webhook":
                validate_webhook_url(channel.get("url", ""), self.webhook_hosts)
        return self._write(ctx, "subscription", body, action="subscription.create", key=key,
                           request_id=request_id)

    def ingest_notification(self, ctx, body, *, key, request_id):
        event_type = body.get("event_type", "")
        if not event_type.startswith(EVENT_PREFIXES):
            raise GovernanceError("unknown canonical event type", code="invalid_event_type")
        body = dict(body)
        body.setdefault("read", False)
        body.setdefault("delivery_status", "pending")
        return self._write(ctx, "notification", body, action="notification.ingest", key=key,
                           request_id=request_id)

    # Canonical Track B producer ingress. The accepted, redacted event, outbox
    # row and tamper-evident audit row commit as one transaction.
    def ingest_canonical_event(self, ctx, event, *, key, request_id, encoded_size):
        if not key or len(key) < 8 or len(key) > 255:
            raise GovernanceError("Idempotency-Key must contain 8 to 255 characters",
                                  code="idempotency_key_required")
        validate_event(event, encoded_size)
        if event["project_id"] != ctx.project_id or event["domain_id"] != ctx.domain_id:
            raise Forbidden("event scope must match the scoped Keystone token")
        accepted = normalize_event(event)
        digest = event_hash(self.store, accepted)
        received = now()
        record = {"event_id": accepted["event_id"], "status": "accepted",
                  "received_at": received, "event": accepted}
        with self.store.transaction() as db:
            prior = db.execute(
                "SELECT domain_id,project_id,request_hash,body FROM canonical_events WHERE event_id=?",
                (accepted["event_id"],)).fetchone()
            if prior:
                if prior[0] != ctx.domain_id or prior[1] != ctx.project_id or prior[2] != digest:
                    raise Conflict("event_id was already used for different content or scope")
                return self.store.decode(prior[3]), True
            prior_key = db.execute(
                "SELECT event_id,request_hash,body FROM canonical_events WHERE project_id=? AND idempotency_key=?",
                (ctx.project_id, key)).fetchone()
            if prior_key:
                if prior_key[0] != accepted["event_id"] or prior_key[1] != digest:
                    raise Conflict("Idempotency-Key was already used for a different event")
                return self.store.decode(prior_key[2]), True
            db.execute(
                "INSERT INTO canonical_events(event_id,domain_id,project_id,idempotency_key,request_hash,status,body,received_at) "
                "VALUES(?,?,?,?,?,'accepted',?,?)",
                (accepted["event_id"], ctx.domain_id, ctx.project_id, key, digest,
                 self.store.encode(record), received))
            db.execute(
                "INSERT INTO outbox(id,project_id,event_type,dedup_key,payload,status,available_at,created_at) "
                "VALUES(?,?,?,?,?,'pending',?,?)",
                (accepted["event_id"], ctx.project_id, accepted["event_type"],
                 "canonical-event:" + accepted["event_id"], self.store.encode(accepted), received, received))
            audit = {
                "event_id": str(uuid4()), "occurred_at": received, "received_at": received,
                "domain_id": ctx.domain_id, "project_id": ctx.project_id,
                "actor": {"type": "user", "id": ctx.user_id}, "service": "governance",
                "action": "canonical_event.ingest",
                "target": {"type": "canonical_event", "id": accepted["event_id"]},
                "outcome": "success", "request_id": request_id,
                "operation_id": accepted["operation_id"], "changes": {},
            }
            prior_hash = db.execute(
                "SELECT integrity_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            previous = prior_hash[0] if prior_hash else "0" * 64
            integrity = hashlib.sha256((previous + self.store.encode(audit)).encode()).hexdigest()
            audit["integrity_hash"] = integrity
            db.execute(
                "INSERT INTO audit_events(event_id,project_id,occurred_at,body,previous_hash,integrity_hash) "
                "VALUES(?,?,?,?,?,?)", (audit["event_id"], ctx.project_id, received,
                                         self.store.encode(audit), previous, integrity))
        return record, False

    def get_canonical_event(self, ctx, event_id):
        row = self.store.connection.execute(
            "SELECT body FROM canonical_events WHERE event_id=? AND domain_id=? AND project_id=?",
            (event_id, ctx.domain_id, ctx.project_id)).fetchone()
        if not row:
            raise NotFound("canonical event not found")
        return self.store.decode(row[0])

    def page_canonical_events(self, ctx, *, limit=50, cursor=None, status=None):
        if limit < 1 or limit > 200:
            raise GovernanceError("limit must be between 1 and 200")
        if status and status not in {"accepted"}:
            raise GovernanceError("unsupported event status", code="invalid_status")
        offset = decode_cursor(cursor)
        query = "SELECT body FROM canonical_events WHERE project_id=?"
        params = [ctx.project_id]
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY received_at DESC,event_id LIMIT ? OFFSET ?"
        params.extend([limit + 1, offset])
        rows = list(self.store.connection.execute(query, params))
        items = [self.store.decode(row[0]) for row in rows[:limit]]
        return {"items": items, "next": encode_cursor(offset + limit) if len(rows) > limit else None}

    # FinOps
    def create_rate_card(self, ctx, body, *, key, request_id):
        if not ctx.system_reader:
            raise Forbidden("rate cards require a system role")
        Decimal(str(body["unit_price"]))
        return self._write(ctx, "rate_card", body, action="rate_card.create", key=key,
                           request_id=request_id)

    def record_usage(self, ctx, body, *, key, request_id):
        quantity = Decimal(str(body["quantity"]))
        price = Decimal(str(body["unit_price"]))
        rated = dict(body)
        rated["quantity"] = str(quantity)
        rated["cost"] = str((quantity * price).quantize(Decimal("0.000001"), ROUND_HALF_EVEN))
        rated.setdefault("coverage", "complete")
        return self._write(ctx, "usage", rated, action="usage.record", key=key,
                           request_id=request_id)

    def page_usage_ledger(self, ctx, *, limit=50, cursor=None, period=None, meter=None):
        if limit < 1 or limit > 200:
            raise GovernanceError("limit must be between 1 and 200")
        offset = decode_cursor(cursor)
        query = ("SELECT sample_id,period,meter,quantity,unit_price,cost,rate_version,created_at "
                 "FROM cost_ledger WHERE project_id=?")
        params = [ctx.project_id]
        if period:
            query += " AND period LIKE ?"
            params.append(f"{period}%")
        if meter:
            query += " AND meter=?"
            params.append(meter)
        query += " ORDER BY period,sample_id LIMIT ? OFFSET ?"
        params.extend([limit + 1, offset])
        rows = list(self.store.connection.execute(query, params))
        missing = [row[0] for row in self.store.connection.execute(
            "SELECT DISTINCT r.meter FROM usage_raw r LEFT JOIN cost_ledger l "
            "ON l.project_id=r.project_id AND l.sample_id=r.sample_id "
            "WHERE r.project_id=? AND l.sample_id IS NULL ORDER BY r.meter", (ctx.project_id,))]
        checkpoint = self.store.connection.execute(
            "SELECT watermark,updated_at FROM telemetry_checkpoints "
            "WHERE source='cloudkitty-v2' AND project_id=?", (ctx.project_id,)).fetchone()
        return {"items": [dict(row) for row in rows[:limit]],
                "next": encode_cursor(offset + limit) if len(rows) > limit else None,
                "coverage": "incomplete" if missing else "complete", "missing_meters": missing,
                "watermark": checkpoint[0] if checkpoint else None,
                "watermark_updated_at": checkpoint[1] if checkpoint else None,
                "currency": "DCN-CREDIT", "billing": False}

    def create_budget(self, ctx, body, *, key, request_id):
        amount = Decimal(str(body["amount"]))
        if amount <= 0:
            raise GovernanceError("budget amount must be positive")
        thresholds = body.get("thresholds", [50, 80, 90, 100])
        if thresholds != sorted(set(thresholds)) or any(x <= 0 for x in thresholds):
            raise GovernanceError("thresholds must be sorted unique positive values")
        return self._write(ctx, "budget", body, action="budget.create", key=key,
                           request_id=request_id)

    # Certificates and secret rotation store references/state only.
    def create_certificate_policy(self, ctx, body, *, key, request_id):
        if "private_key" in body or "secret" in body:
            raise GovernanceError("secret material must be stored in Barbican", code="secret_material_forbidden")
        domains = body.get("domains") or []
        if not domains or len(domains) > 20:
            raise GovernanceError("one to twenty certificate domains are required")
        policy = dict(body)
        policy["phase"] = "pending_authorization"
        return self._write(ctx, "certificate_policy", policy, action="certificate.issue", key=key,
                           request_id=request_id)

    def create_rotation_policy(self, ctx, body, *, key, request_id):
        if not str(body.get("secret_ref", "")).startswith("barbican://"):
            raise GovernanceError("secret_ref must be a Barbican reference")
        policy = dict(body)
        policy.update({"phase": "candidate_pending", "active_version": 1})
        return self._write(ctx, "rotation_policy", policy, action="secret.rotate", key=key,
                           request_id=request_id)

    # Audit
    def append_audit(self, ctx, *, action, target, outcome, request_id, operation_id=None, changes=None):
        event = {
            "event_id": str(uuid4()), "occurred_at": now(), "received_at": now(),
            "domain_id": ctx.domain_id, "project_id": ctx.project_id,
            "actor": {"type": "user", "id": ctx.user_id}, "service": "governance",
            "action": action, "target": safe_projection(target), "outcome": outcome,
            "request_id": request_id, "operation_id": operation_id,
            "changes": safe_projection(changes or {}),
        }
        with self.store.transaction() as db:
            prior = db.execute("SELECT integrity_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
            previous = prior[0] if prior else "0" * 64
            digest = hashlib.sha256((previous + self.store.encode(event)).encode()).hexdigest()
            event["integrity_hash"] = digest
            db.execute("INSERT INTO audit_events(event_id,project_id,occurred_at,body,previous_hash,integrity_hash) VALUES(?,?,?,?,?,?)",
                       (event["event_id"], ctx.project_id, event["occurred_at"], self.store.encode(event), previous, digest))
        return event

    def search_audit(self, ctx, *, project_id=None, action=None):
        project_id = project_id or ctx.project_id
        ctx.require_project(project_id)
        rows = self.store.connection.execute(
            "SELECT body FROM audit_events WHERE project_id=? ORDER BY seq DESC", (project_id,))
        events = [self.store.decode(row[0]) for row in rows]
        return [event for event in events if not action or event["action"] == action]

    def verify_audit_chain(self) -> bool:
        previous = "0" * 64
        for row in self.store.connection.execute("SELECT body,previous_hash,integrity_hash FROM audit_events ORDER BY seq"):
            event = self.store.decode(row[0])
            embedded = event.pop("integrity_hash", None)
            expected = hashlib.sha256((previous + self.store.encode(event)).encode()).hexdigest()
            if row[1] != previous or row[2] != expected or embedded != expected:
                return False
            previous = row[2]
        return True

    # Tag policy
    def create_tag_policy(self, ctx, body, *, key, request_id):
        for tag_key in set(body.get("defaults", {})) | set(body.get("required", [])):
            if not TAG_KEY.fullmatch(tag_key):
                raise GovernanceError(f"invalid tag key: {tag_key}")
            if tag_key.startswith("system/") and not ctx.system_reader:
                raise Forbidden("system tags require a system role")
        return self._write(ctx, "tag_policy", body, action="tag_policy.create", key=key,
                           request_id=request_id)

    def resolve_tags(self, ctx, user_tags, policies):
        tags = dict(user_tags)
        user_keys = set(tags)
        if any(key.startswith("system/") or key.startswith("dcn.ssu.ac.kr/") for key in tags):
            raise Forbidden("reserved tags cannot be supplied by users")
        if any(not TAG_KEY.fullmatch(key) for key in tags):
            raise GovernanceError("tag key violates canonical syntax")
        for policy in sorted(policies, key=lambda item: {"platform": 0, "domain": 1, "project": 2}[item["scope"]]):
            for key, value in policy.get("defaults", {}).items():
                if not key.startswith("system/"):
                    if key not in user_keys:
                        tags[key] = value
            missing = [key for key in policy.get("required", []) if key not in tags]
            if missing:
                raise GovernanceError("required tags missing: " + ",".join(sorted(missing)), code="required_tags_missing")
        tags.update({
            "dcn.ssu.ac.kr/project-id": ctx.project_id,
            "dcn.ssu.ac.kr/domain-id": ctx.domain_id,
        })
        return tags


def webhook_signature(secret: bytes, timestamp: str, payload: bytes) -> str:
    return hmac.new(secret, timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
