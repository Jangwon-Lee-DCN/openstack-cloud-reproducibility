import unittest
from decimal import Decimal

from governance_api.store import Store
from governance_worker.finops import Budget, BudgetReconciler, DeterministicBudgetEvents, SQLiteBudgetEvents


class BudgetTests(unittest.TestCase):
    def test_thresholds_emit_once_and_reset_by_period(self):
        events = DeterministicBudgetEvents()
        reconciler = BudgetReconciler(events)
        august = Budget("b", "d", "p", "2026-08", Decimal("100"))
        self.assertEqual(reconciler.evaluate(august, Decimal("91")), [50, 80, 90])
        self.assertEqual(reconciler.evaluate(august, Decimal("99")), [])
        september = Budget("b", "d", "p", "2026-09", Decimal("100"))
        self.assertEqual(reconciler.evaluate(september, Decimal("51")), [50])
        self.assertEqual(len(events.events), 4)

    def test_sqlite_threshold_and_outbox_are_atomic_and_deduplicated(self):
        store = Store()
        reconciler = BudgetReconciler(SQLiteBudgetEvents(store))
        budget = Budget("b", "d", "p", "2026-08", Decimal("100"))
        self.assertEqual(reconciler.evaluate(budget, Decimal("81")), [50, 80])
        self.assertEqual(reconciler.evaluate(budget, Decimal("90")), [90])
        self.assertEqual(store.connection.execute("SELECT count(*) FROM budget_events").fetchone()[0], 3)
        self.assertEqual(store.connection.execute("SELECT count(*) FROM outbox").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
