import unittest
from unittest.mock import patch

from governance_api.store import Store
from governance_worker.cloudkitty import CloudKittyCollector


class Client:
    def request(self, path):
        assert path.startswith("/v1/storage/dataframes?")
        return 200, {"dataframes": [{"begin": "2026-08-01T00:00:00Z",
                     "end": "2026-08-01T01:00:00Z", "tenant_id": "p",
                     "resources": [{"service": "instance", "volume": "2", "rating": "2",
                                     "desc": {"project_id": "p", "id": "vm-1"}}]}]}


class CloudKittyTests(unittest.TestCase):
    def test_reprocess_is_idempotent_and_ledger_uses_decimal_rate(self):
        collector = CloudKittyCollector("http://cloudkitty", "token")
        collector.client = Client()
        store = Store()
        first = collector.collect(store, "p", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
        second = collector.collect(store, "p", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(LedgerRepository(store).entries("p")[0]["cost"], "2.000000")


from governance_api.telemetry import LedgerRepository

if __name__ == "__main__":
    unittest.main()
