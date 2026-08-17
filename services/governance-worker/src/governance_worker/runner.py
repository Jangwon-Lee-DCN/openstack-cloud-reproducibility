from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta

from governance_api.outbox import OutboxRepository
from governance_api.store import Store
from governance_api.providers import ProviderError
from .real import initialize_real_integrations
from .cloudkitty import CloudKittyCollector
from .delivery import NotificationEventBus, SmtpSender, WebhookSender
from .finops import Budget, BudgetReconciler, SQLiteBudgetEvents
from decimal import Decimal


class RealScheduler:
    def __init__(self, store: Store, event_bus, *, owner="governance-worker", finops=None):
        self.outbox = OutboxRepository(store)
        self.event_bus = event_bus
        self.owner = owner
        self.finops = finops

    def run_once(self) -> dict:
        claimed = self.outbox.claim(self.owner, limit=100, lease_seconds=30)
        result = {"claimed": len(claimed), "delivered": 0, "retried": 0, "dead": 0}
        for item in claimed:
            try:
                self.event_bus.publish({"id": item.id, "project_id": item.project_id,
                                        "event_type": item.event_type, "payload": item.payload})
                self.outbox.complete(item.id, self.owner)
                result["delivered"] += 1
            except Exception as exc:
                state = self.outbox.fail(item.id, self.owner, type(exc).__name__)
                result["dead" if state == "dead" else "retried"] += 1
        result["finops_projects"] = 0
        if self.finops:
            budget_rows = list(self.outbox.store.connection.execute(
                "SELECT id,domain_id,project_id,body FROM resources WHERE kind='budget' ORDER BY project_id,id"))
            projects = sorted({row[2] for row in budget_rows})
            now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
            begin = now.replace(day=1).isoformat().replace("+00:00", "Z")
            end = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            for project_id in projects:
                try:
                    self.finops.collect(self.outbox.store, project_id, begin, end)
                    result["finops_projects"] += 1
                except ProviderError:
                    result["finops_blocked"] = "cloudkitty_no_data_or_unavailable"
            period = now.strftime("%Y-%m")
            evaluator = BudgetReconciler(SQLiteBudgetEvents(self.outbox.store))
            for row in budget_rows:
                body = self.outbox.store.decode(row[3])
                budget_period = body.get("period", period)
                spend = sum((Decimal(entry[0]) for entry in self.outbox.store.connection.execute(
                    "SELECT cost FROM cost_ledger WHERE project_id=? AND period LIKE ?",
                    (row[2], f"{budget_period}%"))), Decimal("0"))
                evaluator.evaluate(Budget(row[0], row[1], row[2], budget_period,
                                          Decimal(str(body["amount"])),
                                          tuple(body.get("thresholds", [50, 80, 90, 100]))), spend)
        return result


def notification_bus(store, rabbit):
    webhook = None
    if os.getenv("GOVERNANCE_WEBHOOK_SIGNING_KEY"):
        webhook = WebhookSender(
            os.environ["GOVERNANCE_WEBHOOK_SIGNING_KEY"].encode(),
            set(filter(None, os.getenv("GOVERNANCE_WEBHOOK_ALLOWED_HOSTS", "").split(","))),
            allow_http_test_host=os.getenv("GOVERNANCE_WEBHOOK_HTTP_TEST_HOST", ""))
    smtp = None
    if os.getenv("GOVERNANCE_SMTP_HOST"):
        smtp = SmtpSender(
            os.environ["GOVERNANCE_SMTP_HOST"], int(os.getenv("GOVERNANCE_SMTP_PORT", "587")),
            set(filter(None, os.getenv("GOVERNANCE_SMTP_ALLOWED_DOMAINS", "").split(","))),
            starttls=os.getenv("GOVERNANCE_SMTP_STARTTLS", "true").lower() == "true")
    return NotificationEventBus(rabbit, store, webhook, smtp)


def main():
    if os.getenv("GOVERNANCE_MODE", "production") != "development":
        raise SystemExit("development boundary is required")
    if os.getenv("GOVERNANCE_PROVIDER_MODE", "disabled") != "real":
        raise SystemExit("real providers are required; refusing fake execution")
    integrations = initialize_real_integrations()
    store = Store(os.getenv("GOVERNANCE_DB_PATH", "/var/lib/governance/governance.db"))
    collector = CloudKittyCollector(os.environ["GOVERNANCE_CLOUDKITTY_URL"], integrations.token)
    event_bus = notification_bus(store, integrations.event_bus)
    scheduler = RealScheduler(store, event_bus, finops=collector)
    if os.getenv("GOVERNANCE_RUN_ONCE") == "1":
        scheduler.run_once()
        return
    interval = max(1, int(os.getenv("GOVERNANCE_POLL_SECONDS", "5")))
    while True:
        scheduler.run_once()
        time.sleep(interval)


if __name__ == "__main__":
    main()
