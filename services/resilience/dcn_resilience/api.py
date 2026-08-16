"""Minimal WSGI API for the isolated development slice.

Authentication is deliberately fail-closed: the development Gateway must pass
verified project identity. Production integration will replace this boundary
with Keystone middleware and OPA, and is not part of this feature deployment.
"""

from __future__ import annotations

import json
import os
from wsgiref.simple_server import make_server

from .contracts import FakeEventClient, FakeOperationClient
from .engine import Engine
from .store import Journal
from .workflows import DevelopmentAdapter


def build_app(database: str | None = None):
    engine = Engine(Journal(database or os.environ.get("RESILIENCE_DB", "/data/resilience.db")),
                    FakeOperationClient(), FakeEventClient(), DevelopmentAdapter())

    def app(environ, start_response):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        if path == "/healthz":
            return respond(start_response, 200, {"status": "ok", "track_a": "fake/v1alpha1", "track_b": "fake/v1alpha1"})
        project_id = environ.get("HTTP_X_VERIFIED_PROJECT_ID", "")
        if not project_id:
            return respond(start_response, 401, {"error": "verified project identity required"})
        try:
            if method == "POST" and path.startswith("/v1/runs/"):
                kind = path.removeprefix("/v1/runs/")
                size = int(environ.get("CONTENT_LENGTH") or 0)
                if size > 65536:
                    raise ValueError("request too large")
                body = json.loads(environ["wsgi.input"].read(size) or b"{}")
                operation = engine.submit(kind, project_id, environ.get("HTTP_IDEMPOTENCY_KEY", ""), body)
                return respond(start_response, 201, public_operation(operation))
            if method == "GET" and path.startswith("/v1/operations/"):
                operation = engine.journal.get(path.rsplit("/", 1)[-1], project_id)
                return respond(start_response, 200, public_operation(operation))
            return respond(start_response, 404, {"error": "not found"})
        except KeyError:
            return respond(start_response, 404, {"error": "not found"})
        except ValueError as exc:
            return respond(start_response, 400, {"error": str(exc)})
        except Exception:
            return respond(start_response, 500, {"error": "operation failed; use the correlation id"})
    return app


def public_operation(value):
    return {key: value[key] for key in ("id", "kind", "state", "correlation_id", "result", "steps")}


def respond(start_response, status, body):
    payload = json.dumps(body, sort_keys=True).encode()
    start_response(f"{status} {'OK' if status < 400 else 'Error'}", [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
    return [payload]


def main():
    make_server("0.0.0.0", int(os.environ.get("PORT", "8080")), build_app()).serve_forever()


if __name__ == "__main__":
    main()
