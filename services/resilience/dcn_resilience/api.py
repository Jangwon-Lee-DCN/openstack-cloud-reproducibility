"""Minimal WSGI API for the isolated development slice.

Authentication is deliberately fail-closed: the development Gateway must pass
verified project identity. Production integration will replace this boundary
with Keystone middleware and OPA, and is not part of this feature deployment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from .config import Config
from .controlplane import COLLECTIONS, make_controller
from .contracts import FakeEventClient, FakeOperationClient
from .engine import Engine
from .store import Journal
from .workflows import DevelopmentAdapter
from .integrations import integration_readiness
from .integrations import KeystoneSession
from .cross_track import TrackAHttpClient, TrackBHttpClient


def _contract_schema(name: str) -> dict:
    candidates = (Path(__file__).parents[1] / "contracts" / name, Path("/app/contracts") / name)
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise RuntimeError(f"missing embedded contract schema {name}")


def _engine(config: Config, database: str):
    journal = Journal(database)
    if config.mode == "development":
        return Engine(journal, FakeOperationClient(), FakeEventClient(), DevelopmentAdapter()), None
    session = KeystoneSession(config.integration["KEYSTONE_AUTH_URL"],
                              config.integration["KEYSTONE_APPLICATION_CREDENTIAL_ID"],
                              config.integration["KEYSTONE_APPLICATION_CREDENTIAL_SECRET"])
    session.authenticate()
    operations = TrackAHttpClient(config.integration["TRACK_A_URL"], session, journal,
                                  _contract_schema("track-a.operation.v1alpha1.schema.json"))
    events = TrackBHttpClient(config.integration["TRACK_B_URL"], session, journal,
                              _contract_schema("track-b.event.v1alpha1.schema.json"))
    return Engine(journal, operations, events, DevelopmentAdapter()), session


def build_app(database: str | None = None):
    config = Config.from_env()
    engine, session = _engine(config, database or config.database)
    controller = make_controller(engine)

    def app(environ, start_response):
        path, method = environ.get("PATH_INFO", ""), environ.get("REQUEST_METHOD", "GET")
        if path == "/healthz":
            return respond(start_response, 200, {"status": "ok", "mode": config.mode,
                           "track_a": "fake/v1alpha1" if config.mode == "development" else "real/v1alpha1",
                           "track_b": "fake/v1alpha1" if config.mode == "development" else "real/v1alpha1"})
        if path in {"/readyz", "/v1/capabilities"}:
            value = ({"ready": True, "mode": "development", "destructive_actions": "fenced"}
                     if config.mode == "development" else integration_readiness(config))
            return respond(start_response, 200 if value["ready"] else 503, value)
        if path == "/openapi.json":
            return respond(start_response, 200, openapi_document())
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
                if session:
                    if project_id != session.project_id:
                        return respond(start_response, 403, {"error": "project does not match application credential scope"})
                    body.update({"domain_id": session.domain_id, "requested_by": session.user_id})
                operation = engine.submit(kind, project_id, environ.get("HTTP_IDEMPOTENCY_KEY", ""), body)
                return respond(start_response, 201, public_operation(operation))
            if method == "GET" and path.startswith("/v1/operations/"):
                operation = engine.journal.get(path.rsplit("/", 1)[-1], project_id)
                return respond(start_response, 200, public_operation(operation))
            segments = [segment for segment in path.split("/") if segment]
            if len(segments) >= 2 and segments[0] == "v1" and segments[1] in COLLECTIONS:
                collection = segments[1]
                if len(segments) == 2 and method == "POST":
                    body = read_body(environ)
                    return respond(start_response, 201, controller.store.create(collection, project_id, body))
                if len(segments) == 2 and method == "GET":
                    query = parse_qs(environ.get("QUERY_STRING", ""))
                    page = controller.store.list(collection, project_id, int(query.get("limit", [50])[0]),
                                                 query.get("marker", [None])[0])
                    page["next"] = (f"/v1/{collection}?limit={query.get('limit', [50])[0]}&marker={page['next_marker']}"
                                    if page["next_marker"] else None)
                    return respond(start_response, 200, page)
                if len(segments) == 3 and method == "GET":
                    return respond(start_response, 200, controller.store.get(collection, project_id, segments[2]))
                if len(segments) == 3 and method == "PUT":
                    body = read_body(environ)
                    generation = int(environ.get("HTTP_IF_MATCH_GENERATION", "0"))
                    return respond(start_response, 200, controller.store.update(collection, project_id, segments[2], body, generation))
                if len(segments) == 3 and method == "DELETE":
                    controller.store.delete(collection, project_id, segments[2])
                    return respond(start_response, 204, None)
                if len(segments) == 5 and segments[3:] == ["actions", "reconcile"] and method == "POST":
                    return respond(start_response, 202, controller.reconcile(collection, project_id, segments[2]))
            return respond(start_response, 404, {"error": "not found"})
        except KeyError:
            return respond(start_response, 404, {"error": "not found"})
        except ValueError as exc:
            return respond(start_response, 400, {"error": str(exc)})
        except Exception:
            return respond(start_response, 500, {"error": "operation failed; use the correlation id"})
    app.controller = controller
    app.database = database or config.database
    return app


def read_body(environ):
    size = int(environ.get("CONTENT_LENGTH") or 0)
    if size > 65536:
        raise ValueError("request too large")
    value = json.loads(environ["wsgi.input"].read(size) or b"{}")
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def openapi_document():
    paths = {
        "/healthz": {"get": {"summary": "Health", "security": [], "responses": {"200": {"description": "Healthy"}}}},
        "/openapi.json": {"get": {"summary": "OpenAPI document", "security": [], "responses": {"200": {"description": "OpenAPI 3.1 document"}}}},
        "/readyz": {"get": {"summary": "Dependency readiness", "security": [], "responses": {"200": {"description": "Ready"}, "503": {"description": "Integration blocked"}}}},
        "/v1/capabilities": {"get": {"summary": "Read-only integration capabilities", "security": [], "responses": {"200": {"description": "Capabilities"}, "503": {"description": "Integration blocked"}}}},
    }
    for collection in sorted(COLLECTIONS):
        paths[f"/v1/{collection}"] = {
            "get": {"summary": f"List {collection}", "parameters": [
                {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
                {"name": "marker", "in": "query", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Project-scoped page"}}},
            "post": {"summary": f"Create {collection}", "requestBody": {"required": True,
                "content": {"application/json": {"schema": {"type": "object"}}}},
                "responses": {"201": {"description": "Created resource"}}}}
        paths[f"/v1/{collection}/{{id}}"] = {
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "get": {"summary": f"Get {collection}", "responses": {"200": {"description": "Resource"}, "404": {"description": "Not found"}}},
            "put": {"summary": f"Update {collection}", "parameters": [{"name": "If-Match-Generation", "in": "header", "required": True, "schema": {"type": "integer"}}],
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "Updated"}, "400": {"description": "Generation conflict"}}},
            "delete": {"summary": f"Delete {collection}", "responses": {"204": {"description": "Deleted"}}}}
        paths[f"/v1/{collection}/{{id}}/actions/reconcile"] = {"post": {
            "summary": "Reconcile resource", "responses": {"202": {"description": "Reconciliation result"}}}}
    return {"openapi": "3.1.0", "info": {"title": "DCN Resilience API", "version": "0.2.0"},
            "security": [{"verifiedProject": []}], "paths": paths, "components": {"securitySchemes": {
                "verifiedProject": {"type": "apiKey", "in": "header", "name": "X-Verified-Project-ID"}}}}


def public_operation(value):
    return {key: value[key] for key in ("id", "kind", "state", "correlation_id", "result", "steps")}


def respond(start_response, status, body):
    payload = b"" if body is None else json.dumps(body, sort_keys=True).encode()
    start_response(f"{status} {'OK' if status < 400 else 'Error'}", [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
    return [payload]


def main():
    app = build_app()
    if os.environ.get("RESILIENCE_SCHEDULER", "true").lower() == "true":
        threading.Thread(target=_scheduler_loop, args=(app.database,), daemon=True).start()
    make_server("0.0.0.0", int(os.environ.get("PORT", "8080")), app).serve_forever()


def _scheduler_controller(database):
    engine, _ = _engine(Config.from_env(), database)
    return make_controller(engine)


def _scheduler_loop(database):
    # SQLite connections are created and owned inside this thread. Sharing the
    # WSGI connection would violate sqlite3 thread affinity and silently stop
    # scheduled backup/DR reconciliation while health checks stayed green.
    controller = _scheduler_controller(database)
    while True:
        controller.tick()
        time.sleep(int(os.environ.get("RESILIENCE_SCHEDULER_INTERVAL", "30")))


if __name__ == "__main__":
    main()
