from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
from uuid import uuid4

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


class WebhookSender:
    def __init__(self, key: bytes, allowed_hosts: set[str], *, allow_http_test_host=""):
        if len(key) < 32:
            raise WorkflowError("webhook signing key must contain at least 32 bytes")
        self.key = key
        self.allowed_hosts = {item.lower() for item in allowed_hosts if item}
        self.allow_http_test_host = allow_http_test_host.lower()

    def send(self, delivery_id: str, url: str, payload: dict) -> dict:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if host not in self.allowed_hosts:
            raise WorkflowError("webhook destination denied")
        if parsed.scheme != "https" and not (
                parsed.scheme == "http" and host == self.allow_http_test_host):
            raise WorkflowError("webhook transport must use HTTPS")
        if contains_sensitive(payload):
            raise WorkflowError("secret material cannot enter webhook payloads")
        encoded = canonical_payload(payload)
        timestamp = int(datetime.now(UTC).timestamp())
        nonce = uuid4().hex
        signature = sign_webhook(self.key, timestamp, nonce, encoded)
        request = Request(url, data=encoded, method="POST", headers={
            "Content-Type": "application/json",
            "X-DCN-Timestamp": str(timestamp),
            "X-DCN-Nonce": nonce,
            "X-DCN-Signature": signature,
            "X-DCN-Delivery-ID": delivery_id,
        })
        try:
            with urlopen(request, timeout=10) as response:
                if response.status < 200 or response.status >= 300:
                    raise WorkflowError("webhook delivery rejected")
        except HTTPError as exc:
            raise WorkflowError(f"webhook_http_{exc.code}") from exc
        except (OSError, TimeoutError) as exc:
            raise WorkflowError("webhook_transport_failed") from exc
        return {"delivery_id": delivery_id, "timestamp": timestamp, "nonce": nonce}


class SmtpSender:
    def __init__(self, host: str, port: int, allowed_domains: set[str], *, starttls=True):
        self.host, self.port = host, port
        self.allowed_domains = {item.lower() for item in allowed_domains if item}
        self.starttls = starttls

    def send(self, delivery_id: str, recipient: str, subject: str, context: dict):
        if any(character in recipient + subject for character in "\r\n"):
            raise WorkflowError("SMTP header injection rejected")
        parts = recipient.rsplit("@", 1)
        if len(parts) != 2 or parts[1].lower() not in self.allowed_domains:
            raise WorkflowError("SMTP recipient domain denied")
        if contains_sensitive(context):
            raise WorkflowError("secret material cannot enter notification templates")
        message = EmailMessage()
        message["From"] = "notifications@dcn.ssu.ac.kr"
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = f"<{delivery_id}@dcn.ssu.ac.kr>"
        message.set_content(json.dumps(context, sort_keys=True, indent=2))
        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as client:
                if self.starttls:
                    client.starttls(context=ssl.create_default_context())
                client.send_message(message)
        except (OSError, smtplib.SMTPException, socket.timeout) as exc:
            raise WorkflowError("smtp_transport_failed") from exc
        return {"delivery_id": delivery_id, "recipient": recipient}


class NotificationEventBus:
    """Fan out durable outbox events to Rabbit and project subscriptions."""

    def __init__(self, rabbit, store, webhook: WebhookSender | None, smtp: SmtpSender | None):
        self.rabbit, self.store, self.webhook, self.smtp = rabbit, store, webhook, smtp

    def publish(self, event: dict):
        # Rabbit consumers deduplicate on the canonical event/outbox id.
        self.rabbit.publish(event)
        rows = self.store.connection.execute(
            "SELECT id,body FROM resources WHERE kind='subscription' AND project_id=? ORDER BY id",
            (event["project_id"],)).fetchall()
        for subscription_id, encoded in rows:
            subscription = self.store.decode(encoded)
            event_types = set(subscription.get("event_types", ["*"]))
            if "*" not in event_types and event["event_type"] not in event_types:
                continue
            for index, channel in enumerate(subscription.get("channels", [])):
                delivery_id = f'{event["id"]}:{subscription_id}:{index}'
                payload = {"event_id": event["id"], "event_type": event["event_type"],
                           "project_id": event["project_id"], "payload": event["payload"]}
                if channel.get("type") == "webhook" and self.webhook:
                    self.webhook.send(delivery_id, channel["url"], payload)
                elif channel.get("type") == "smtp" and self.smtp:
                    self.smtp.send(delivery_id, channel["recipient"],
                                   channel.get("subject", event["event_type"]), payload)
                else:
                    raise WorkflowError("notification channel is unavailable")
