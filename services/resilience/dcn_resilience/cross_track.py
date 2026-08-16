"""Durable, project-scoped Track A/B HTTP consumers."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import EVENT_CONTRACT, OPERATION_CONTRACT, OPERATION_STATES
from .integrations import IntegrationError, KeystoneSession, _request
from .store import Journal


class DeliveryError(IntegrationError):
    pass


def _same_identifier(left: str, right: str) -> bool:
    try:
        return uuid.UUID(left) == uuid.UUID(right)
    except (ValueError, TypeError, AttributeError):
        return left == right


@dataclass
class CircuitBreaker:
    threshold: int = 3
    cooldown_seconds: float = 30
    failures: int = 0
    opened_at: float = 0

    def before(self) -> None:
        if self.failures >= self.threshold and time.time() - self.opened_at < self.cooldown_seconds:
            raise DeliveryError("target circuit is open")

    def success(self) -> None:
        self.failures = 0; self.opened_at = 0

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()


class DurableDelivery:
    def __init__(self, journal: Journal, target: str, contract: str, sender: Callable,
                 *, attempts: int = 3, base_delay: float = .05, sleeper=time.sleep,
                 breaker: CircuitBreaker | None = None):
        self.journal, self.target, self.contract, self.sender = journal, target, contract, sender
        self.max_attempts, self.base_delay, self.sleeper = attempts, base_delay, sleeper
        self.breaker = breaker or CircuitBreaker()

    def send(self, key: str, operation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.journal.enqueue_delivery(self.target, key, operation_id, self.contract, payload)
        item = self.journal.delivery(self.target, key)
        if item["state"] == "delivered":
            return item["response"]
        last = "delivery was not attempted"
        for attempt in range(item["attempts"], self.max_attempts):
            try:
                self.breaker.before()
                response = self.sender(payload, key)
                self.breaker.success()
                self.journal.mark_delivery(self.target, key, "delivered", response=response)
                return response
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                self.breaker.failure()
                terminal = attempt + 1 >= self.max_attempts
                delay = self.base_delay * (2 ** attempt)
                self.journal.mark_delivery(self.target, key, "dead-letter" if terminal else "retry",
                                           error=last, delay=delay)
                if not terminal:
                    self.sleeper(delay)
        raise DeliveryError(last)


def _stable_key(operation_id: str, label: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return f"track-c:{operation_id}:{label}:{digest}"


class TrackAHttpClient:
    contract_version = OPERATION_CONTRACT
    _paths = {
        "RUNNING": ("VALIDATING", "SCHEDULED", "RUNNING"),
        "SUCCEEDED": ("SUCCEEDED",), "FAILED": ("FAILED",),
    }

    def __init__(self, url: str, session: KeystoneSession, journal: Journal,
                 schema: dict[str, Any], transport=_request, **delivery_options):
        self.url, self.session, self.transport = url.rstrip("/"), session, transport
        self.schema = schema
        self.delivery = DurableDelivery(journal, "track-a", OPERATION_CONTRACT, self._send, **delivery_options)

    def _headers(self, key: str | None = None) -> dict[str, str]:
        if not self.session.token:
            self.session.authenticate()
        headers = {"X-Auth-Token": self.session.token, "X-DCN-Authorization-Class": "project-write"}
        if key: headers["Idempotency-Key"] = key
        return headers

    def _get(self, operation_id: str) -> dict[str, Any]:
        _, value, _ = self.transport(f"{self.url}/v1/operations/{operation_id}", headers=self._headers())
        required = set(self.schema.get("required", ()))
        if required - value.keys() or value.get("contract_version") != OPERATION_CONTRACT \
                or value.get("state") not in OPERATION_STATES:
            raise DeliveryError("Track A response violates canonical operation contract")
        if not _same_identifier(value["project_id"], self.session.project_id):
            raise DeliveryError("Track A operation escaped application credential project scope")
        return value

    def _send(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        current = self._get(payload["operation_id"])
        target = payload["state"]
        if current["state"] == target:
            return current
        for state in self._paths[target]:
            if current["state"] == state: continue
            progress = 100 if state == "SUCCEEDED" else max(current["progress"], 5 if state == "VALIDATING" else 10 if state == "SCHEDULED" else 20)
            body = {"expected_revision": current["revision"], "state": state, "progress": progress,
                    "current_step": payload["detail"].get("kind"), "checkpoint": payload["detail"]}
            if state == "FAILED": body["error"] = payload["detail"]
            _, current, _ = self.transport(f"{self.url}/v1/operations/{payload['operation_id']}/transition",
                                           "POST", self._headers(f"{key}:{state}"), body)
            if current.get("contract_version") != OPERATION_CONTRACT or current.get("state") != state:
                raise DeliveryError("Track A transition response violates canonical contract")
        return current

    def transition(self, operation_id: str, state: str, detail: dict[str, Any]) -> None:
        if state not in self._paths:
            raise ValueError("unsupported Track A transition")
        payload = {"operation_id": operation_id, "state": state, "detail": detail}
        self.delivery.send(_stable_key(operation_id, state, payload), operation_id, payload)


class TrackBHttpClient:
    contract_version = EVENT_CONTRACT

    def __init__(self, url: str, session: KeystoneSession, journal: Journal,
                 schema: dict[str, Any], transport=_request, **delivery_options):
        self.url, self.session, self.transport = url.rstrip("/"), session, transport
        self.schema = schema
        self.delivery = DurableDelivery(journal, "track-b", EVENT_CONTRACT, self._send, **delivery_options)

    def _send(self, event: dict[str, Any], key: str) -> dict[str, Any]:
        required = set(self.schema.get("required", ()))
        if required - event.keys() or event.get("contract_version") != EVENT_CONTRACT:
            raise DeliveryError("Track B request violates canonical event contract")
        if not self.session.token: self.session.authenticate()
        if event["project_id"] != self.session.project_id:
            raise DeliveryError("Track B event escaped application credential project scope")
        headers = {"X-Auth-Token": self.session.token, "X-Project-Id": self.session.project_id,
                   "Idempotency-Key": key, "X-Openstack-Request-Id": event["request_id"]}
        _, response, _ = self.transport(f"{self.url}/v1/events", "POST", headers, event)
        if response.get("event", {}).get("contract_version") != EVENT_CONTRACT:
            raise DeliveryError("Track B response omitted canonical contract version")
        return response

    def emit(self, event_type: str, envelope: dict[str, Any]) -> None:
        if event_type != envelope.get("event_type"):
            raise ValueError("event type mismatch")
        self.delivery.send(_stable_key(envelope["operation_id"], event_type, envelope),
                           envelope["operation_id"], envelope)
