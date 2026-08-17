import unittest

from governance_dashboard.client import COLLECTIONS, GovernanceClient


class ClientContractTest(unittest.TestCase):
    def test_only_development_endpoint_is_accepted(self):
        GovernanceClient("https://p1-governance-services.dev.dcn.ssu.ac.kr", {})
        for endpoint in ("http://localhost", "https://cloud.dcn.ssu.ac.kr"):
            with self.assertRaises(ValueError):
                GovernanceClient(endpoint, {})

    def test_all_track_b_sections_exist(self):
        names = {name for name, _ in COLLECTIONS}
        self.assertTrue({"notifications", "usage", "budgets", "certificate-policies",
                         "aws-price-profiles", "aws-calibration-profiles",
                         "rotation-policies", "audit-events", "tag-policies"}.issubset(names))


if __name__ == "__main__":
    unittest.main()
