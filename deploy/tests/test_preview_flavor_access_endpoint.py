from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PreviewFlavorAccessEndpointTests(unittest.TestCase):
    def test_catalog_project_placeholders_are_resolved(self):
        script = (
            ROOT / "deploy/scripts/reconcile-preview-service-catalog.sh"
        ).read_text()

        self.assertIn(
            'endpoint.replace("%(project_id)s", admin_project_id)', script
        )
        self.assertIn(
            'endpoint.replace("%(tenant_id)s", admin_project_id)', script
        )
        self.assertLess(
            script.index('endpoint.replace("%(project_id)s", admin_project_id)'),
            script.index('url = endpoint.rstrip("/")'),
        )


if __name__ == "__main__":
    unittest.main()
