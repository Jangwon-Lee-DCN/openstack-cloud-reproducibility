from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response

app = FastAPI(title="DCN project Loki gateway", docs_url=None, redoc_url=None)
from .policy import project_selector

LOKI_URL = os.getenv("LOKI_URL", "http://loki-gateway.monitoring.svc.cluster.local")
KEYSTONE_URL = os.getenv("KEYSTONE_URL", "https://keystone-api.openstack.svc.cluster.local:5000/v3")
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").lower() == "true"
ALLOWED_PATHS = {
    "/loki/api/v1/query",
    "/loki/api/v1/query_range",
    "/loki/api/v1/labels",
    "/loki/api/v1/label",
    "/loki/api/v1/series",
}


async def token_project(token: str) -> str:
    headers = {"X-Subject-Token": token, "X-Auth-Token": token}
    async with httpx.AsyncClient(verify=VERIFY_TLS, timeout=10) as client:
        response = await client.get(f"{KEYSTONE_URL.rstrip('/')}/auth/tokens", headers=headers)
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="invalid OpenStack token")
    body: dict[str, Any] = response.json()
    project_id = body.get("token", {}).get("project", {}).get("id")
    if not project_id:
        raise HTTPException(status_code=403, detail="a project-scoped token is required")
    return str(project_id)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(
    path: str,
    request: Request,
    x_auth_token: str | None = Header(default=None),
) -> Response:
    route = "/" + path
    if route not in ALLOWED_PATHS and not route.startswith("/loki/api/v1/label/"):
        raise HTTPException(status_code=404, detail="unsupported Loki API")
    if not x_auth_token:
        raise HTTPException(status_code=401, detail="X-Auth-Token is required")
    project_id = await token_project(x_auth_token)
    params = list(request.query_params.multi_items())
    secured: list[tuple[str, str]] = []
    for key, value in params:
        if key in {"query", "match[]"}:
            try:
                value = project_selector(value, project_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        secured.append((key, value))
    has_selector = any(key in {"query", "match[]"} for key, _ in secured)
    if route.endswith(("/query", "/query_range")) and not has_selector:
        raise HTTPException(status_code=400, detail="query selector is required")
    if not has_selector:
        selector = project_selector("{}", project_id)
        secured.append(("match[]" if route.endswith("/series") else "query", selector))
    headers = {"X-Scope-OrgID": "openstack", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        upstream = await client.request(
            request.method,
            f"{LOKI_URL.rstrip('/')}{route}",
            params=secured,
            content=await request.body(),
            headers=headers,
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
