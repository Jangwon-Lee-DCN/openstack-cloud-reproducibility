from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PreviewFlavorAccessContractTests(unittest.TestCase):
    def test_access_reconciliation_uses_openstack_client(self):
        script = (
            ROOT / "deploy/scripts/reconcile-preview-service-catalog.sh"
        ).read_text()

        self.assertIn("openstack flavor access list gpu.passthrough.preview", script)
        self.assertIn(
            'openstack flavor unset --project "$project_id" '
            "gpu.passthrough.preview",
            script,
        )
        self.assertIn("[[ ${#gpu_flavor_access[@]} -eq 1 ]]", script)
        self.assertNotIn("urllib.request", script)


if __name__ == "__main__":
    unittest.main()
