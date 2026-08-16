from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import GovernanceError
from .security import RequestContext
from .service import GovernanceService
from .store import Store


ROUTES = {
    "/v1/subscriptions": ("subscription", "create_subscription"),
    "/v1/notifications": ("notification", "ingest_notification"),
    "/v1/rate-cards": ("rate_card", "create_rate_card"),
    "/v1/usage": ("usage", "record_usage"),
    "/v1/budgets": ("budget", "create_budget"),
    "/v1/certificate-policies": ("certificate_policy", "create_certificate_policy"),
    "/v1/rotation-policies": ("rotation_policy", "create_rotation_policy"),
    "/v1/tag-policies": ("tag_policy", "create_tag_policy"),
}


def context(headers) -> RequestContext:
    required = ("X-Domain-Id", "X-Project-Id", "X-User-Id")
    if any(not headers.get(item) for item in required):
        raise GovernanceError("Keystone-authenticated identity headers are required", code="identity_required")
    return RequestContext(headers["X-Domain-Id"], headers["X-Project-Id"], headers["X-User-Id"],
                          frozenset(filter(None, headers.get("X-Roles", "").split(","))))


class Handler(BaseHTTPRequestHandler):
    service: GovernanceService
    server_version = "dcn-governance/0.1"

    def log_message(self, fmt, *args):
        # Never log headers or bodies: they can contain credentials.
        print(json.dumps({"remote": self.client_address[0], "message": fmt % args}))

    def reply(self, status, body):
        encoded = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        try:
            if self.path == "/healthz":
                return self.reply(200, {"status": "ok"})
            ctx = context(self.headers)
            if self.path == "/v1/audit-events":
                return self.reply(200, {"items": self.service.search_audit(ctx)})
            route = ROUTES.get(self.path)
            if not route:
                return self.reply(404, {"error": {"code": "not_found"}})
            return self.reply(200, {"items": self.service.list_resources(ctx, route[0])})
        except GovernanceError as exc:
            self.reply(exc.status, {"error": {"code": exc.code, "message": str(exc)}})

    def do_POST(self):
        try:
            ctx = context(self.headers)
            route = ROUTES.get(self.path)
            if not route:
                return self.reply(404, {"error": {"code": "not_found"}})
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_048_576:
                raise GovernanceError("request is too large", code="payload_too_large")
            body = json.loads(self.rfile.read(length) or b"{}")
            result = getattr(self.service, route[1])(
                ctx, body, key=self.headers.get("Idempotency-Key", ""),
                request_id=self.headers.get("X-Openstack-Request-Id", "req-unknown"),
            )
            self.reply(201, result)
        except GovernanceError as exc:
            self.reply(exc.status, {"error": {"code": exc.code, "message": str(exc)}})
        except (ValueError, json.JSONDecodeError):
            self.reply(400, {"error": {"code": "invalid_json"}})


def main():
    store = Store(os.getenv("GOVERNANCE_DB_PATH", "/var/lib/governance/governance.db"))
    Handler.service = GovernanceService(
        store, webhook_hosts=os.getenv("GOVERNANCE_WEBHOOK_ALLOWED_HOSTS", "").split(","))
    address = os.getenv("GOVERNANCE_LISTEN", "0.0.0.0")
    port = int(os.getenv("GOVERNANCE_PORT", "8080"))
    ThreadingHTTPServer((address, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
