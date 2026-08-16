from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .workflows import WorkflowError


SENSITIVE_KEYS = {"password", "token", "secret", "private_key", "authorization", "cookie"}


def contains_sensitive(value) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in SENSITIVE_KEYS or contains_sensitive(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(contains_sensitive(item) for item in value)
    return False


def canonical_payload(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def sign_webhook(key: bytes, timestamp: int, nonce: str, payload: bytes) -> str:
    material = f"{timestamp}.{nonce}.".encode() + payload
    return hmac.new(key, material, hashlib.sha256).hexdigest()


@dataclass
class ReplayCache:
    seen: dict[tuple[str, str], int] = field(default_factory=dict)

    def consume(self, consumer_id: str, nonce: str, expires_at: int, now: int):
        self.seen = {key: expiry for key, expiry in self.seen.items() if expiry >= now}
        key = (consumer_id, nonce)
        if key in self.seen:
            raise WorkflowError("webhook replay detected")
        self.seen[key] = expires_at


def verify_webhook(key: bytes, consumer_id: str, timestamp: int, nonce: str, payload: bytes,
                   signature: str, replay: ReplayCache, *, now: int, max_age=300):
    if timestamp > now + 30 or now - timestamp > max_age:
        raise WorkflowError("webhook timestamp outside acceptance window")
    expected = sign_webhook(key, timestamp, nonce, payload)
    if not hmac.compare_digest(expected, signature):
        raise WorkflowError("invalid webhook signature")
    replay.consume(consumer_id, nonce, timestamp + max_age, now)


def validate_destination(url: str, allowed_hosts: set[str], resolver) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or host not in allowed_hosts:
        raise WorkflowError("webhook destination denied")
    addresses = resolver(host)
    if not addresses:
        raise WorkflowError("webhook destination did not resolve")
    for text in addresses:
        address = ipaddress.ip_address(text)
        if not address.is_global:
            raise WorkflowError("webhook resolved to a non-public address")
    return url


@dataclass
class WebhookDevelopmentFixture:
    key: bytes
    allowed_hosts: set[str]
    resolver: object
    deliveries: list[dict] = field(default_factory=list)

    def send(self, consumer_id: str, url: str, payload: dict, *, timestamp: int, nonce: str):
        validate_destination(url, self.allowed_hosts, self.resolver)
        if contains_sensitive(payload):
            raise WorkflowError("secret material cannot enter webhook payloads")
        encoded = canonical_payload(payload)
        record = {
            "consumer_id": consumer_id, "url": url, "timestamp": timestamp, "nonce": nonce,
            "signature": sign_webhook(self.key, timestamp, nonce, encoded), "payload": payload,
        }
        self.deliveries.append(record)
        return record


@dataclass
class SmtpDevelopmentFixture:
    allowed_domains: set[str]
    messages: list[dict] = field(default_factory=list)

    def send(self, recipient: str, subject: str, template_id: str, context: dict):
        if any(character in recipient + subject for character in "\r\n"):
            raise WorkflowError("SMTP header injection rejected")
        parts = recipient.rsplit("@", 1)
        if len(parts) != 2 or parts[1].lower() not in self.allowed_domains:
            raise WorkflowError("SMTP recipient domain denied")
        if contains_sensitive(context):
            raise WorkflowError("secret material cannot enter notification templates")
        record = {"recipient": recipient, "subject": subject, "template_id": template_id,
                  "context": dict(context)}
        self.messages.append(record)
        return record
