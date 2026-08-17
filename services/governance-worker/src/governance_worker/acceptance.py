"""Destructive-only-to-prefixed resources FinOps development acceptance."""
from __future__ import annotations

import json
import os
import time
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from .real import application_credential_token
from .cloudkitty import SHOWBACK_RATES
from governance_api.telemetry import DeterministicTelemetrySource, LedgerRepository, Rate
from governance_api.store import Store


STATE = Path("/var/lib/governance/finops-acceptance.json")


def call(url, token, *, method="GET", body=None, headers=None, expected=(200, 201, 202, 204)):
    request_headers = {"Accept": "application/json", "X-Auth-Token": token, **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode()
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, method=method, headers=request_headers)
    with urlopen(request, timeout=15) as response:
        if response.status not in expected:
            raise RuntimeError(f"unexpected HTTP status {response.status}")
        return response.status, json.loads(response.read() or b"{}")


def identity():
    token = application_credential_token(
        os.environ["GOVERNANCE_KEYSTONE_URL"],
        os.environ["GOVERNANCE_APPLICATION_CREDENTIAL_ID"],
        os.environ["GOVERNANCE_APPLICATION_CREDENTIAL_SECRET"])
    return token, os.environ["GOVERNANCE_KEYSTONE_PROJECT_ID"]


def require_absent(url, token, headers=None):
    try:
        call(url, token, headers=headers)
    except HTTPError as exc:
        if exc.code == 404:
            return
        raise
    raise RuntimeError("acceptance resource remains after cleanup")


def seed():
    if STATE.exists():
        raise RuntimeError("acceptance state already exists; cleanup first")
    token, project_id = identity()
    resource_id = str(uuid4())
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    measure_time = now - timedelta(hours=1)
    _, resource = call(os.environ["GOVERNANCE_GNOCCHI_URL"] + "/v1/resource/generic", token,
        method="POST", body={"id": resource_id, "project_id": project_id,
                             "user_id": "governance-finops-acceptance",
                             "metrics": {
                                 "governance.acceptance": {"archive_policy_name": "low"},
                                 "governance.acceptance.undefined": {"archive_policy_name": "low"}}})
    metric_id = resource["metrics"]["governance.acceptance"]
    undefined_metric_id = resource["metrics"]["governance.acceptance.undefined"]
    call(os.environ["GOVERNANCE_GNOCCHI_URL"] + f"/v1/metric/{metric_id}/measures", token,
         method="POST", body=[{"timestamp": measure_time.isoformat(), "value": 2.0}])
    call(os.environ["GOVERNANCE_GNOCCHI_URL"] + f"/v1/metric/{undefined_metric_id}/measures", token,
         method="POST", body=[{"timestamp": measure_time.isoformat(), "value": 1.0}])
    period = now.strftime("%Y-%m")
    _, budget = call("http://127.0.0.1:8080/v1/budgets", token, method="POST",
        headers={"X-Project-Id": project_id, "Idempotency-Key": f"finops-{resource_id}"},
        body={"amount": "1.000000", "period": period, "thresholds": [50, 100],
              "name": "governance-finops-acceptance"})
    snapshot = {"resource_id": resource_id, "metric_id": metric_id,
                "undefined_metric_id": undefined_metric_id,
                "budget_id": budget["id"], "budget_revision": budget["revision"],
                "project_id": project_id, "period": period,
                "ledger_count": 0, "ledger_cost": 0.0}
    STATE.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
    print(json.dumps({"seed": "complete", "project_id": project_id,
                      "reset_timestamp": (measure_time - timedelta(hours=1)).isoformat()},
                     sort_keys=True))


def setup():
    if not STATE.exists():
        raise RuntimeError("seed acceptance resources before collection")
    token, project_id = identity()
    snapshot = json.loads(STATE.read_text(encoding="utf-8"))
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    period = snapshot["period"]
    begin = now.replace(day=1).isoformat().replace("+00:00", "Z")
    end = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    deadline = time.monotonic() + 900
    cloudkitty_total = 0
    ledger = {}
    while time.monotonic() < deadline:
        query = urlencode({"tenant_id": project_id, "begin": begin, "end": end})
        try:
            _, frames = call(os.environ["GOVERNANCE_CLOUDKITTY_URL"] +
                             f"/v1/storage/dataframes?{query}", token)
            cloudkitty_total = len(frames.get("dataframes", []))
        except HTTPError as exc:
            if exc.code not in (404,):
                raise
        _, ledger = call("http://127.0.0.1:8080/v1/usage-summary?" + urlencode({"period": period}), token,
                         headers={"X-Project-Id": project_id})
        if cloudkitty_total and ledger.get("items"):
            break
        time.sleep(10)
    if not cloudkitty_total or not ledger.get("items"):
        raise RuntimeError("timed out waiting for Gnocchi -> CloudKitty -> Governance ledger")
    if ledger.get("coverage") != "incomplete" or \
            "governance.acceptance.undefined" not in ledger.get("missing_meters", []):
        raise RuntimeError("undefined meter was not preserved as incomplete")
    snapshot.update({"ledger_count": len(ledger["items"]),
                     "ledger_cost": sum(float(item["cost"]) for item in ledger["items"])})
    STATE.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
    print(json.dumps({"cloudkitty_total": cloudkitty_total, **snapshot}, sort_keys=True))


def verify():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    token, project_id = identity()
    _, ledger = call("http://127.0.0.1:8080/v1/usage-summary?" + urlencode({"period": state["period"]}), token,
                     headers={"X-Project-Id": project_id})
    count = len(ledger["items"])
    cost = sum(float(item["cost"]) for item in ledger["items"])
    if count != state["ledger_count"] or cost != state["ledger_cost"]:
        raise RuntimeError("reprocess changed immutable ledger")
    rates = {meter: Rate("dcn-showback-v1", meter, price)
             for meter, price in SHOWBACK_RATES.items()}
    rates["governance.acceptance.undefined"] = Rate(
        "dcn-showback-v1-late", "governance.acceptance.undefined", Decimal("0.250000"))
    late = LedgerRepository(Store(os.environ["GOVERNANCE_DB_PATH"])).aggregate(
        "cloudkitty-v1", project_id, DeterministicTelemetrySource([]), rates)
    if late["inserted"] != 1 or late["coverage"] != "complete":
        raise RuntimeError("undefined meter late-rating did not reconcile exactly once")
    database = sqlite3.connect(os.environ["GOVERNANCE_DB_PATH"])
    threshold_count = database.execute(
        "SELECT count(*) FROM budget_events WHERE budget_id=?", (state["budget_id"],)).fetchone()[0]
    notification_count = database.execute(
        "SELECT count(*) FROM outbox WHERE event_type='budget.threshold' AND project_id=?",
        (project_id,)).fetchone()[0]
    if threshold_count != 2 or notification_count < 2:
        raise RuntimeError("budget thresholds were not connected to notification outbox")
    print(json.dumps({"duplicate_reprocess": "stable", "ledger_count_before_late_rate": count,
                      "ledger_cost": cost, "coverage": ledger["coverage"],
                      "late_rate_inserted": late["inserted"], "late_rate_coverage": late["coverage"],
                      "budget_thresholds": threshold_count,
                      "notification_events": notification_count}, sort_keys=True))


def cleanup():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    token, project_id = identity()
    call(os.environ["GOVERNANCE_GNOCCHI_URL"] + f"/v1/resource/generic/{state['resource_id']}",
         token, method="DELETE")
    call("http://127.0.0.1:8080/v1/budgets/" + state["budget_id"], token, method="DELETE",
         headers={"X-Project-Id": project_id, "If-Match": str(state["budget_revision"]),
                  "Idempotency-Key": "finops-cleanup-" + state["resource_id"]})
    require_absent(os.environ["GOVERNANCE_GNOCCHI_URL"] +
                   f"/v1/resource/generic/{state['resource_id']}", token)
    require_absent("http://127.0.0.1:8080/v1/budgets/" + state["budget_id"], token,
                   {"X-Project-Id": project_id})
    STATE.unlink()
    print(json.dumps({"cleanup": "complete", "resource_remaining": 0, "budget_remaining": 0}))


if __name__ == "__main__":
    action = os.environ.get("GOVERNANCE_FINOPS_ACCEPTANCE", "")
    {"seed": seed, "setup": setup, "verify": verify, "cleanup": cleanup}.get(
        action, lambda: (_ for _ in ()).throw(
            RuntimeError("set GOVERNANCE_FINOPS_ACCEPTANCE=seed|setup|verify|cleanup")))()
