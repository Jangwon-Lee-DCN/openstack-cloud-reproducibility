from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class KeystoneAdminCredentialTests(unittest.TestCase):
    def test_admin_credential_reconciler_is_locked_and_secret_safe(self):
        script = (ROOT / "deploy/scripts/reconcile-keystone-admin-credential.sh").read_text()
        self.assertIn("dcn-production-deploy-lock", script)
        self.assertIn("openstack token issue", script)
        self.assertIn("jsonpath='{.data.OS_PASSWORD}'", script)
        self.assertIn("base64 -d", script)
        self.assertIn("exec -i", script)
        self.assertIn('identity.update_user(user["id"], {"password": password})', script)
        self.assertNotIn("--password", script)

    def test_full_reconciler_repairs_admin_auth_after_keystone(self):
        script = (ROOT / "deploy/scripts/reconcile-full-stack.sh").read_text()
        self.assertEqual(script.count('reconcile-keystone-admin-credential.sh'), 2)


if __name__ == "__main__":
    unittest.main()
