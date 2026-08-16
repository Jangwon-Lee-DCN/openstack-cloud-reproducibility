import tempfile
import unittest
from pathlib import Path

from governance_worker.migrate import apply_migrations


class Result:
    def __init__(self, value=None): self.value = value
    def fetchone(self): return (self.value,)
    def fetchall(self): return [(1,)]


class Connection:
    def __init__(self): self.statements = []
    def execute(self, statement):
        self.statements.append(statement)
        if "to_regclass" in statement: return Result(True)
        if "SELECT version" in statement: return Result()
        return Result()


class MigrationTests(unittest.TestCase):
    def test_applies_only_versions_missing_from_durable_table(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "001_old.sql").write_text("old")
            Path(directory, "002_new.sql").write_text("new")
            connection = Connection()
            self.assertEqual(apply_migrations(connection, directory), [2])
            self.assertIn("new", connection.statements)
            self.assertNotIn("old", connection.statements)


if __name__ == "__main__":
    unittest.main()
