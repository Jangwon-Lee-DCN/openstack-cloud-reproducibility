import json
import os
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .errors import CoreError
from .service import CoreService
from .store import Store


def build_service():
    key = os.environ.get("CORE_APPROVAL_SIGNING_KEY", "")
    if not key:
        raise RuntimeError("CORE_APPROVAL_SIGNING_KEY is required")
    return CoreService(Store(os.environ.get("CORE_DB_PATH", "/data/core.db")), key.encode())


class Handler(BaseHTTPRequestHandler):
    service = None
    server_version = "dcn-core-orchestrator/0.1"

    def log_message(self, fmt, *args):
        print(json.dumps({"remote": self.client_address[0], "message": fmt % args}))

    def body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def identity(self):
        project = self.headers.get("X-Project-Id")
        user = self.headers.get("X-User-Id")
        if not project or not user:
            raise CoreError(401, "IDENTITY_REQUIRED", "validated project and user identity headers are required")
        return project, user

    def send_json(self, status, payload, headers=None):
        raw = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers(); self.wfile.write(raw)

    def dispatch(self):
        path = urlparse(self.path)
        if path.path == "/healthz":
            return 200, {"status": "ok"}, {}
        project, user = self.identity()
        body = self.body() if self.command in {"POST", "PUT", "DELETE"} else {}
        query = parse_qs(path.query)
        if self.command == "GET" and path.path == "/v1/operations":
            return 200, {"items": self.service.list_operations(project, (query.get("state") or [None])[0])}, {}
        match = re.fullmatch(r"/v1/operations/([^/]+)(?:/(events|cancel|retry))?", path.path)
        if match:
            ident, action = match.groups()
            if self.command == "GET" and action == "events": return 200, {"items": self.service.operation_events(project, ident)}, {}
            if self.command == "GET" and not action: return 200, self.service.get_operation(project, ident), {}
            if self.command == "POST" and action == "cancel": return 202, self.service.cancel_operation(project, ident), {}
            if self.command == "POST" and action == "retry":
                op, created = self.service.retry_operation(project, ident, self.headers.get("Idempotency-Key"))
                return 202, op, {"Location": f"/v1/operations/{op['id']}"}
        match = re.fullmatch(r"/v1/preflight/(instances|auto-scaling-groups|deletions)", path.path)
        if self.command == "POST" and match:
            return 200, self.service.preflight(project, match.group(1).rstrip("s"), body), {}
        if self.command == "POST" and path.path == "/v1/launch-templates":
            return 201, self.service.create_template(project, user, body), {}
        match = re.fullmatch(r"/v1/launch-templates/([^/]+)(?:/(versions|default-version))?", path.path)
        if match:
            ident, action = match.groups()
            if self.command == "GET": return 200, self.service.get_template(project, ident), {}
            if self.command == "POST" and action == "versions": return 201, self.service.add_template_version(project, user, ident, body), {}
            if self.command == "PUT" and action == "default-version": return 200, self.service.set_default_version(project, ident, body.get("version")), {}
        if self.command == "POST" and path.path == "/v1/auto-scaling-groups":
            return 201, self.service.create_asg(project, body), {}
        match = re.fullmatch(r"/v1/auto-scaling-groups/([^/]+)(?:/events)?", path.path)
        if match:
            ident = match.group(1)
            if self.command == "GET": return 200, self.service.get_asg(project, ident), {}
            if self.command == "POST": return 202, self.service.scaling_event(project, ident, body.get("event_id"), body.get("adjustment")), {}
        match = re.fullmatch(r"/v1/resources/([^/]+)/([^/]+)/deletion-protection", path.path)
        if self.command == "PUT" and match:
            return 200, self.service.set_protection(project, user, *match.groups(), body.get("deletion_protected", False), body.get("reason")), {}
        match = re.fullmatch(r"/v1/resources/([^/]+)/([^/]+)", path.path)
        if self.command == "DELETE" and match:
            return 202, self.service.recycle(project, user, *match.groups(), body.get("retention_days", 7)), {}
        if self.command == "GET" and path.path == "/v1/recycle-bin": return 200, {"items": self.service.list_recycle(project)}, {}
        match = re.fullmatch(r"/v1/recycle-bin/([^/]+)/restore", path.path)
        if self.command == "POST" and match: return 202, self.service.restore(project, match.group(1)), {}
        if self.command == "POST" and path.path == "/v1/operations":
            op, created = self.service.create_operation(project, body["region_id"], body["action"], body["target_type"], body.get("payload", {}), self.headers.get("Idempotency-Key"), body.get("target_id"))
            return 202, op, {"Location": f"/v1/operations/{op['id']}", "X-Idempotent-Replay": str(not created).lower()}
        raise CoreError(404, "ROUTE_NOT_FOUND", "route was not found")

    def handle_method(self):
        try:
            status, payload, headers = self.dispatch()
            self.send_json(status, payload, headers)
        except CoreError as exc:
            self.send_json(exc.status, {"error": {"code": exc.code, "message": exc.message}})
        except (KeyError, json.JSONDecodeError):
            self.send_json(400, {"error": {"code": "REQUEST_INVALID", "message": "request body is invalid"}})
        except Exception:
            traceback.print_exc()
            self.send_json(500, {"error": {"code": "INTERNAL_ERROR", "message": "request failed"}})

    do_GET = do_POST = do_PUT = do_DELETE = handle_method


def main():
    Handler.service = build_service()
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
