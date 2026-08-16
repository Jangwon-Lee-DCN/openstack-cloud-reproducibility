from __future__ import annotations

import base64
import hashlib
from copy import deepcopy

from jsonschema import Draft202012Validator, FormatChecker

from .errors import Conflict, GovernanceError, NotFound
from .security import safe_projection


EVENT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://dcn.ssu.ac.kr/contracts/track-b.event.v1alpha1.schema.json",
    "title": "Track B Canonical Event v1alpha1",
    "type": "object", "additionalProperties": False,
    "required": ["contract_version", "event_id", "event_type", "occurred_at", "domain_id",
                 "project_id", "actor_id", "resource", "severity", "operation_id",
                 "correlation_id", "request_id", "payload"],
    "properties": {
        "contract_version": {"const": "track-b.event.v1alpha1"},
        "event_id": {"type": "string", "format": "uuid"},
        "event_type": {"type": "string", "enum": [
            "resource.changed", "notification.delivery.succeeded", "notification.delivery.failed",
            "budget.threshold.crossed", "certificate.renewal.succeeded", "certificate.renewal.failed",
            "credential.rotation.succeeded", "credential.rotation.failed", "audit.export.succeeded",
            "audit.export.failed", "tag.drift.detected", "tag.drift.reconciled"]},
        "occurred_at": {"type": "string", "format": "date-time"},
        "domain_id": {"type": "string", "minLength": 1},
        "project_id": {"type": "string", "minLength": 1},
        "actor_id": {"type": "string", "minLength": 1},
        "resource": {"type": "object", "additionalProperties": False,
                     "required": ["type", "id"], "properties": {
                         "type": {"type": "string", "minLength": 1},
                         "id": {"type": "string", "format": "uuid"}}},
        "severity": {"type": "string", "enum": ["INFO", "WARNING", "ERROR", "CRITICAL"]},
        "operation_id": {"type": "string", "format": "uuid"},
        "correlation_id": {"type": "string", "format": "uuid"},
        "request_id": {"type": "string", "minLength": 1},
        "payload": {"type": "object", "additionalProperties": True},
    },
}
VALIDATOR = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())
MAX_EVENT_BYTES = 262_144
MAX_PAYLOAD_DEPTH = 8
MAX_PAYLOAD_ITEMS = 512
MAX_STRING_BYTES = 16_384


def validate_event(event, encoded_size: int):
    if encoded_size > MAX_EVENT_BYTES:
        raise GovernanceError("canonical event exceeds 256 KiB", code="payload_too_large", status=413)
    errors = sorted(VALIDATOR.iter_errors(event), key=lambda item: list(item.path))
    if errors:
        raise GovernanceError("canonical event schema validation failed", code="invalid_event_schema")
    items = 0

    def walk(value, depth=0):
        nonlocal items
        if depth > MAX_PAYLOAD_DEPTH:
            raise GovernanceError("event payload nesting is too deep", code="payload_bounds_exceeded")
        if isinstance(value, dict):
            items += len(value)
            for key, child in value.items():
                if len(str(key).encode()) > 256:
                    raise GovernanceError("event payload key is too long", code="payload_bounds_exceeded")
                walk(child, depth + 1)
        elif isinstance(value, list):
            items += len(value)
            for child in value:
                walk(child, depth + 1)
        elif isinstance(value, str) and len(value.encode()) > MAX_STRING_BYTES:
            raise GovernanceError("event payload string is too long", code="payload_bounds_exceeded")
        if items > MAX_PAYLOAD_ITEMS:
            raise GovernanceError("event payload has too many items", code="payload_bounds_exceeded")

    walk(event["payload"])


def normalize_event(event):
    result = deepcopy(event)
    result["payload"] = safe_projection(result["payload"])
    return result


def encode_cursor(offset: int):
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def decode_cursor(cursor):
    if not cursor:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor + "===").decode())
        if offset < 0:
            raise ValueError
        return offset
    except (ValueError, UnicodeError):
        raise GovernanceError("invalid cursor", code="invalid_cursor")


def event_hash(store, event):
    return hashlib.sha256(store.encode(event).encode()).hexdigest()
