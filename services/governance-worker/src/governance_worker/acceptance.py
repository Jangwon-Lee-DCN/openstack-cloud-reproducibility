"""Destructive-only-to-prefixed resources FinOps development acceptance."""
from __future__ import annotations

import json
import os
import time
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from .real import application_credential_token
from .cloudkitty import SHOWBACK_RATES
from governance_api.telemetry import DeterministicTelemetrySource, LedgerRepository, Rate
from governance_api.store import Store


STATE = Path("/var/lib/governance/finops-acceptance.json")
RATING_ARCHIVE_POLICY = "medium"  # Includes CloudKitty's 3600-second granularity.


def checkpoint_for_measure(measure_time: datetime) -> datetime:
    """Return the start of the CloudKitty interval containing the measure.

    CloudKitty collects half-open intervals beginning at its stored checkpoint.
    Starting one period earlier would process the preceding interval and then
    wait for the normal collection period before reaching the acceptance data.
    """
    return measure_time.replace(minute=0, second=0, microsecond=0)


def eligible_measure_time(now: datetime) -> datetime:
    """Choose a measure inside the resource's current active revision.

    Gnocchi's immutable ``revision_start`` is the resource creation time.  A
    backdated measure is therefore invisible to CloudKitty's history query.
    The acceptance-only driver processes this current interval explicitly;
    the production scheduler and its wait window remain untouched.
    """
    return now


def wait_for_metric_measures(urls: list[str], token: str, *, attempts: int = 12,
                             delay: int = 5) -> None:
    """Wait until Gnocchi exposes every asynchronously archived measure."""
    for attempt in range(attempts):
        if all(call(url, token)[1] for url in urls):
            return
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise RuntimeError("Gnocchi measures did not become visible before rating reset")


def call(url, token, *, method="GET", body=None, headers=None, expected=(200, 201, 202, 204)):
    request_headers = {"Accept": "application/json", "X-Auth-Token": token, **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode()
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, method=method, headers=request_headers)
    for attempt in range(6):
        try:
            with urlopen(request, timeout=15) as response:
                if response.status not in expected:
                    raise RuntimeError(f"unexpected HTTP status {response.status}")
                return response.status, json.loads(response.read() or b"{}")
        except (URLError, TimeoutError, OSError):
            if attempt == 5:
                raise
            time.sleep(2)


def identity():
    for attempt in range(6):
        try:
            token = application_credential_token(
                os.environ["GOVERNANCE_KEYSTONE_URL"],
                os.environ["GOVERNANCE_APPLICATION_CREDENTIAL_ID"],
                os.environ["GOVERNANCE_APPLICATION_CREDENTIAL_SECRET"])
            break
        except (URLError, TimeoutError, OSError):
            if attempt == 5:
                raise
            time.sleep(2)
    return token, os.environ["GOVERNANCE_KEYSTONE_PROJECT_ID"]


def require_absent(url, token, headers=None):
    try:
        call(url, token, headers=headers)
    except HTTPError as exc:
        if exc.code == 404:
            return
        raise
    raise RuntimeError("acceptance resource remains after cleanup")


def read_state() -> dict:
    """Read non-secret harness state from an explicit restart-safe fixture."""
    inline = os.environ.get("GOVERNANCE_FINOPS_STATE_JSON")
    return json.loads(inline) if inline else json.loads(STATE.read_text(encoding="utf-8"))


def seed():
    if STATE.exists():
        raise RuntimeError("acceptance state already exists; cleanup first")
    token, project_id = identity()
    resource_id = str(uuid4())
    now = datetime.now(UTC)
    _, resource = call(os.environ["GOVERNANCE_GNOCCHI_URL"] + "/v1/resource/generic", token,
        method="POST", body={"id": resource_id, "project_id": project_id,
                             "user_id": "governance-finops-acceptance",
                             "metrics": {
                                 "governance.acceptance": {
                                     "archive_policy_name": RATING_ARCHIVE_POLICY},
                                 "governance.acceptance.undefined": {
                                     "archive_policy_name": RATING_ARCHIVE_POLICY}}})
    metric_id = resource["metrics"]["governance.acceptance"]
    undefined_metric_id = resource["metrics"]["governance.acceptance.undefined"]
    # Ensure the measure is strictly newer than Gnocchi's server-side
    # resource revision_start, whose precision/order is not client-controlled.
    time.sleep(2)
    measure_time = eligible_measure_time(datetime.now(UTC))
    call(os.environ["GOVERNANCE_GNOCCHI_URL"] + f"/v1/metric/{metric_id}/measures", token,
         method="POST", body=[{"timestamp": measure_time.isoformat(), "value": 2.0}])
    call(os.environ["GOVERNANCE_GNOCCHI_URL"] + f"/v1/metric/{undefined_metric_id}/measures", token,
         method="POST", body=[{"timestamp": measure_time.isoformat(), "value": 1.0}])
    wait_for_metric_measures([
        os.environ["GOVERNANCE_GNOCCHI_URL"] + f"/v1/metric/{metric_id}/measures",
        os.environ["GOVERNANCE_GNOCCHI_URL"] + f"/v1/metric/{undefined_metric_id}/measures",
    ], token)
    period = measure_time.strftime("%Y-%m")
    _, budget = call("http://127.0.0.1:8080/v1/budgets", token, method="POST",
        headers={"X-Project-Id": project_id, "Idempotency-Key": f"finops-{resource_id}"},
        body={"amount": "1.000000", "period": period, "thresholds": [50, 100],
              "name": "governance-finops-acceptance"})
    database = sqlite3.connect(os.environ["GOVERNANCE_DB_PATH"])
    baseline_ledger_ids = [row[0] for row in database.execute(
        "SELECT sample_id FROM cost_ledger WHERE project_id=?", (project_id,))]
    baseline_missing_ids = [row[0] for row in database.execute(
        "SELECT r.sample_id FROM usage_raw r LEFT JOIN cost_ledger l "
        "ON l.project_id=r.project_id AND l.sample_id=r.sample_id "
        "WHERE r.project_id=? AND r.meter=? AND l.sample_id IS NULL",
        (project_id, "governance.acceptance.undefined"))]
    snapshot = {"resource_id": resource_id, "metric_id": metric_id,
                "undefined_metric_id": undefined_metric_id,
                "budget_id": budget["id"], "budget_revision": budget["revision"],
                "project_id": project_id, "period": period,
                "baseline_ledger_ids": baseline_ledger_ids,
                "baseline_missing_ids": baseline_missing_ids}
    STATE.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
    print(json.dumps({"seed": "complete", **snapshot,
                      "reset_timestamp": checkpoint_for_measure(measure_time).isoformat()},
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
        # Refresh the scoped token each poll. Development acceptance includes
        # a processor rollout and must tolerate a transient Keystone/service
        # route convergence without treating an old validation failure as a
        # permanent credential failure.
        token, project_id = identity()
        query = urlencode({"tenant_id": project_id, "begin": begin, "end": end})
        try:
            _, frames = call(os.environ["GOVERNANCE_CLOUDKITTY_URL"] +
                             f"/v1/storage/dataframes?{query}", token)
            cloudkitty_total = len(frames.get("dataframes", []))
        except HTTPError as exc:
            if exc.code not in (401, 404):
                raise
        try:
            _, ledger = call("http://127.0.0.1:8080/v1/usage-summary?" +
                             urlencode({"period": period}), token,
                             headers={"X-Project-Id": project_id})
        except HTTPError as exc:
            if exc.code != 401:
                raise
            ledger = {}
        if cloudkitty_total and ledger.get("items"):
            break
        time.sleep(10)
    if not cloudkitty_total or not ledger.get("items"):
        raise RuntimeError("timed out waiting for Gnocchi -> CloudKitty -> Governance ledger")
    if ledger.get("coverage") != "incomplete" or \
            "governance.acceptance.undefined" not in ledger.get("missing_meters", []):
        raise RuntimeError("undefined meter was not preserved as incomplete")
    baseline = set(snapshot["baseline_ledger_ids"])
    acceptance_items = [item for item in ledger["items"] if item["sample_id"] not in baseline]
    if len(acceptance_items) != 1 or acceptance_items[0]["meter"] != "governance.acceptance":
        raise RuntimeError("acceptance rated sample was not isolated exactly once")
    database = sqlite3.connect(os.environ["GOVERNANCE_DB_PATH"])
    missing_now = {row[0] for row in database.execute(
        "SELECT r.sample_id FROM usage_raw r LEFT JOIN cost_ledger l "
        "ON l.project_id=r.project_id AND l.sample_id=r.sample_id "
        "WHERE r.project_id=? AND r.meter=? AND l.sample_id IS NULL",
        (project_id, "governance.acceptance.undefined"))}
    acceptance_missing = sorted(missing_now - set(snapshot["baseline_missing_ids"]))
    if len(acceptance_missing) != 1:
        raise RuntimeError("acceptance undefined sample was not isolated exactly once")
    snapshot.update({"ledger_items": acceptance_items,
                     "undefined_sample_ids": acceptance_missing})
    STATE.write_text(json.dumps(snapshot, sort_keys=True), encoding="utf-8")
    print(json.dumps({"cloudkitty_total": cloudkitty_total, **snapshot}, sort_keys=True))


def verify():
    state = read_state()
    token, project_id = identity()
    _, ledger = call("http://127.0.0.1:8080/v1/usage-summary?" + urlencode({"period": state["period"]}), token,
                     headers={"X-Project-Id": project_id})
    current = {item["sample_id"]: item for item in ledger["items"]}
    expected = {item["sample_id"]: item for item in state["ledger_items"]}
    if any(current.get(sample_id) != item for sample_id, item in expected.items()):
        raise RuntimeError("reprocess changed immutable ledger")
    rates = {meter: Rate("dcn-showback-v1", meter, price)
             for meter, price in SHOWBACK_RATES.items()}
    rates["governance.acceptance.undefined"] = Rate(
        "dcn-showback-v1-late", "governance.acceptance.undefined", Decimal("0.250000"))
    late = LedgerRepository(Store(os.environ["GOVERNANCE_DB_PATH"])).aggregate(
        "cloudkitty-v1", project_id, DeterministicTelemetrySource([]), rates)
    database = sqlite3.connect(os.environ["GOVERNANCE_DB_PATH"])
    late_count = database.execute(
        "SELECT count(*) FROM cost_ledger WHERE project_id=? AND sample_id IN (%s)" %
        ",".join("?" for _ in state["undefined_sample_ids"]),
        (project_id, *state["undefined_sample_ids"])).fetchone()[0]
    if late_count != 1 or late["coverage"] != "complete":
        raise RuntimeError("undefined meter late-rating did not reconcile exactly once")
    threshold_count = database.execute(
        "SELECT count(*) FROM budget_events WHERE budget_id=?", (state["budget_id"],)).fetchone()[0]
    notification_count = database.execute(
        "SELECT count(*) FROM outbox WHERE event_type='budget.threshold' AND project_id=?",
        (project_id,)).fetchone()[0]
    if threshold_count != 2 or notification_count < 2:
        raise RuntimeError("budget thresholds were not connected to notification outbox")
    print(json.dumps({"duplicate_reprocess": "stable", "ledger_count_before_late_rate": len(expected),
                      "ledger_cost": sum(float(item["cost"]) for item in expected.values()),
                      "coverage": ledger["coverage"],
                      "late_rate_inserted": late["inserted"], "late_rate_coverage": late["coverage"],
                      "budget_thresholds": threshold_count,
                      "notification_events": notification_count}, sort_keys=True))


def cleanup():
    state = read_state()
    token, project_id = identity()
    try:
        call(os.environ["GOVERNANCE_GNOCCHI_URL"] +
             f"/v1/resource/generic/{state['resource_id']}", token, method="DELETE")
    except HTTPError as exc:
        if exc.code != 404:
            raise
    try:
        call("http://127.0.0.1:8080/v1/budgets/" + state["budget_id"], token, method="DELETE",
             headers={"X-Project-Id": project_id, "If-Match": str(state["budget_revision"]),
                      "Idempotency-Key": "finops-cleanup-" + state["resource_id"]})
    except HTTPError as exc:
        if exc.code != 404:
            raise
    require_absent(os.environ["GOVERNANCE_GNOCCHI_URL"] +
                   f"/v1/resource/generic/{state['resource_id']}", token)
    require_absent("http://127.0.0.1:8080/v1/budgets/" + state["budget_id"], token,
                   {"X-Project-Id": project_id})
    STATE.unlink(missing_ok=True)
    print(json.dumps({"cleanup": "complete", "resource_remaining": 0, "budget_remaining": 0}))


if __name__ == "__main__":
    action = os.environ.get("GOVERNANCE_FINOPS_ACCEPTANCE", "")
    {"seed": seed, "setup": setup, "verify": verify, "cleanup": cleanup}.get(
        action, lambda: (_ for _ in ()).throw(
            RuntimeError("set GOVERNANCE_FINOPS_ACCEPTANCE=seed|setup|verify|cleanup")))()
