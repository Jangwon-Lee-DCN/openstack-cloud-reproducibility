import pathlib
import unittest

from governance_api.postgres_contract import OUTBOX_CLAIM_SQL, PostgreSQLSessionContract, TENANT_SCOPE_SQL


class FakeCursor:
    def __init__(self): self.calls = []; self.closed = False
    def execute(self, statement, parameters): self.calls.append((statement, parameters))
    def fetchall(self): return [("id",)]
    def close(self): self.closed = True


class FakeConnection:
    def __init__(self): self.value = FakeCursor(); self.commits = 0; self.rollbacks = 0
    def cursor(self): return self.value
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


class PostgreSQLContractTest(unittest.TestCase):
    def test_migrations_are_transactional_append_only_and_tenant_scoped(self):
        migration_dir = pathlib.Path(__file__).parents[1] / "migrations"
        migrations = sorted(migration_dir.glob("*.sql"))
        self.assertEqual([item.name for item in migrations], ["001_governance.sql", "002_tenant_rls.sql"])
        combined = "\n".join(item.read_text() for item in migrations)
        for migration in migrations:
            text = migration.read_text().strip()
            self.assertTrue(text.startswith("BEGIN;"))
            self.assertTrue(text.endswith("COMMIT;"))
        for required in ("governance_outbox", "governance_cost_ledger", "governance_audit_event",
                         "ENABLE ROW LEVEL SECURITY", "current_setting('dcn.project_id', true)"):
            self.assertIn(required, combined)
        for destructive in ("DROP TABLE", "TRUNCATE", "DELETE FROM"):
            self.assertNotIn(destructive, combined.upper())

    def test_repository_contract_parameterizes_scope_and_uses_skip_locked(self):
        connection = FakeConnection()
        repository = PostgreSQLSessionContract(connection)
        with repository.tenant_transaction("project-id") as cursor:
            rows = repository.claim_outbox(cursor, "worker", 10, 30)
        self.assertEqual(connection.value.calls[0], (TENANT_SCOPE_SQL, ("project-id",)))
        self.assertEqual(connection.value.calls[1][1], (10, "worker", 30))
        self.assertIn("FOR UPDATE SKIP LOCKED", OUTBOX_CLAIM_SQL)
        self.assertEqual(rows, [("id",)])
        self.assertEqual(connection.commits, 1)
        self.assertTrue(connection.value.closed)


if __name__ == "__main__":
    unittest.main()
