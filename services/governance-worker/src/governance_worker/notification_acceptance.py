from __future__ import annotations

import json
import os
from contextlib import redirect_stdout
from io import StringIO
from urllib.request import Request, urlopen
from uuid import uuid4

from governance_api.store import Store
from .real import initialize_real_integrations
from .runner import RealScheduler, notification_bus


def request(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    with urlopen(Request("http://127.0.0.1:8081" + path, data=data,
                         method="GET" if body is None else "POST",
                         headers={"Content-Type": "application/json"}), timeout=5) as response:
        return json.load(response) if response.status != 204 else {}


def main():
    store = Store(os.environ["GOVERNANCE_DB_PATH"])
    # Provider discovery writes a diagnostic JSON line for operators. Keep the
    # acceptance contract itself machine-readable as exactly one JSON object.
    with redirect_stdout(StringIO()):
        integrations = initialize_real_integrations()
    scheduler = RealScheduler(store, notification_bus(store, integrations.event_bus))
    project_id = os.environ["GOVERNANCE_KEYSTONE_PROJECT_ID"]
    subscription_id = "notification-acceptance-subscription"
    run_id = uuid4().hex
    event_ids = [f"notification-acceptance-retry-{run_id}",
                 f"notification-acceptance-dead-{run_id}"]
    now = "2000-01-01T00:00:00Z"
    subscription = {"id": subscription_id, "event_types": ["notification.acceptance"],
                    "channels": [{"type": "webhook", "url": "http://127.0.0.1:8081/events"},
                                 {"type": "smtp", "recipient": "acceptance@dcn.ssu.ac.kr",
                                  "subject": "DCN notification acceptance"}]}
    try:
        with store.transaction() as db:
            db.execute("DELETE FROM resources WHERE kind='subscription' AND id=?", (subscription_id,))
            db.execute("DELETE FROM outbox WHERE id IN (?,?)", event_ids)
            db.execute("INSERT INTO resources(kind,id,domain_id,project_id,revision,body,created_at,updated_at) VALUES(?,?,?,?,1,?,?,?)",
                       ("subscription", subscription_id, "acceptance-domain", project_id,
                        store.encode(subscription), now, now))
            payload = {"event_id": event_ids[0], "event_type": "notification.acceptance",
                       "project_id": project_id, "payload": {"safe": "acceptance"}}
            db.execute("INSERT INTO outbox(id,project_id,event_type,dedup_key,payload,status,attempts,available_at,created_at) VALUES(?,?,?,?,?,'pending',0,?,?)",
                       (event_ids[0], project_id, "notification.acceptance", event_ids[0],
                        store.encode(payload), now, now))
        request("/control/fail-next", {"count": 2})
        for _ in range(3):
            scheduler.run_once()
            with store.transaction() as db:
                db.execute("UPDATE outbox SET available_at=? WHERE id=?", (now, event_ids[0]))
        retry = store.connection.execute("SELECT status,attempts FROM outbox WHERE id=?", (event_ids[0],)).fetchone()
        if tuple(retry) != ("delivered", 2):
            raise RuntimeError(f"retry acceptance failed: {tuple(retry)}")
        payload = {"event_id": event_ids[1], "event_type": "notification.acceptance",
                   "project_id": project_id, "payload": {"safe": "acceptance"}}
        with store.transaction() as db:
            db.execute(
                "INSERT INTO outbox(id,project_id,event_type,dedup_key,payload,status,attempts,available_at,created_at) VALUES(?,?,?,?,?,'pending',0,?,?)",
                (event_ids[1], project_id, "notification.acceptance", event_ids[1],
                 store.encode(payload), now, now))
        request("/control/fail-next", {"count": 10})
        for _ in range(5):
            scheduler.run_once()
            with store.transaction() as db:
                db.execute("UPDATE outbox SET available_at=? WHERE id=?", (now, event_ids[1]))
        dead = store.connection.execute("SELECT status,attempts FROM outbox WHERE id=?", (event_ids[1],)).fetchone()
        if tuple(dead) != ("dead", 5):
            raise RuntimeError(f"DLQ acceptance failed: {tuple(dead)}")
        records = request("/records")
        matching = [item for item in records["webhooks"] if item["payload"]["event_id"] == event_ids[0]]
        smtp = [item for item in records["smtp"] if event_ids[0] in item]
        if len(matching) != 1 or len(smtp) != 1:
            raise RuntimeError("notification sink did not suppress duplicate delivery")
        print(json.dumps({"retry": list(retry), "dead": list(dead),
                          "webhook": len(matching), "smtp": len(smtp)}, sort_keys=True))
    finally:
        with store.transaction() as db:
            db.execute("DELETE FROM resources WHERE kind='subscription' AND id=?", (subscription_id,))
            db.execute("DELETE FROM outbox WHERE id IN (?,?)", event_ids)


if __name__ == "__main__": main()
