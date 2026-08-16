import unittest
from decimal import Decimal

from governance_worker.loops import DeterministicProviders, FakeReconciliationLoops


class ReconciliationLoopTest(unittest.TestCase):
    def test_all_fake_provider_loops_converge(self):
        providers = DeterministicProviders(spend={"budget": Decimal("85")})
        providers.tag_adapter.resources["server"] = (1, {})
        loops = FakeReconciliationLoops(providers)
        self.assertEqual(loops.budget("budget", "2026-08", Decimal("100"), [50, 80, 100]), [50, 80])
        self.assertEqual(loops.budget("budget", "2026-08", Decimal("100"), [50, 80, 100]), [])
        certificate = loops.certificate("cert")
        self.assertEqual(certificate.phase, "active")
        self.assertFalse(certificate.cleanup_required)
        rotation = loops.rotation("rotation", "barbican://fake/v1", {"lb", "app"})
        self.assertEqual(rotation.phase, "active")
        tags = loops.tags("server", {"dcn.ssu.ac.kr/project-id": "p"})
        self.assertTrue(tags.changed)


if __name__ == "__main__":
    unittest.main()
