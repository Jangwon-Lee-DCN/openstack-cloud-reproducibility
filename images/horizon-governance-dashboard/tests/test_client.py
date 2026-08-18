import unittest

from governance_dashboard.client import (ADMIN_COST_COLLECTIONS, COLLECTIONS,
                                         COST_COLLECTIONS, GovernanceClient)


class ClientContractTest(unittest.TestCase):
    def test_only_managed_endpoints_are_accepted(self):
        GovernanceClient("https://p1-governance-services.dev.dcn.ssu.ac.kr", {})
        GovernanceClient("http://governance-api.development-p1-governance-services.svc.cluster.local", {})
        GovernanceClient("http://governance-api.governance-system.svc.cluster.local", {})
        for endpoint in ("http://localhost", "https://cloud.dcn.ssu.ac.kr"):
            with self.assertRaises(ValueError):
                GovernanceClient(endpoint, {})

    def test_all_track_b_sections_exist(self):
        names = {name for name, _ in COLLECTIONS}
        self.assertTrue({"notifications", "usage", "budgets", "certificate-policies",
                         "rotation-policies", "audit-events", "tag-policies"}.issubset(names))
        self.assertNotIn("aws-price-profiles", names)
        self.assertNotIn("aws-calibration-profiles", names)

    def test_cost_management_owns_aws_sections(self):
        self.assertEqual({name for name, _ in COST_COLLECTIONS}, {"usage", "budgets"})
        self.assertEqual({name for name, _ in ADMIN_COST_COLLECTIONS},
                         {"aws-price-profiles", "aws-calibration-profiles"})


if __name__ == "__main__":
    unittest.main()
