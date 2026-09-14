from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PreviewFlavorAccessContractTests(unittest.TestCase):
    def test_access_reconciliation_uses_project_independent_nova_url(self):
        script = (
            ROOT / "deploy/scripts/reconcile-preview-service-catalog.sh"
        ).read_text()

        self.assertIn('r"/v2\\.1(?:/.*)?$", "/v2.1"', script)
        self.assertIn('f"{api_root}/flavors/{flavor_id}/os-flavor-access"', script)
        self.assertIn('"removeTenantAccess"', script)
        self.assertIn("urllib.request", script)
        self.assertNotIn("flavor unset --project", script)


if __name__ == "__main__":
    unittest.main()
