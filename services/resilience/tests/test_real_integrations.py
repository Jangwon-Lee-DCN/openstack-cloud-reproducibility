import os
import unittest
from unittest.mock import patch

from dcn_resilience.config import Config
from dcn_resilience.integrations import (IntegrationError, KeystoneSession, OPAClient,
                                         SERVICE_PROBES, integration_readiness, real_catalog)


class RealIntegrationTests(unittest.TestCase):
    def test_integration_configuration_fails_closed(self):
        with patch.dict(os.environ, {"RESILIENCE_MODE": "integration"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "missing"):
                Config.from_env()

    def test_destructive_flag_cannot_be_enabled(self):
        env = {"RESILIENCE_MODE": "integration", "KEYSTONE_AUTH_URL": "http://keystone",
               "KEYSTONE_APPLICATION_CREDENTIAL_ID": "id", "KEYSTONE_APPLICATION_CREDENTIAL_SECRET": "secret",
               "OPA_URL": "http://opa", "TRACK_A_URL": "http://a", "TRACK_B_URL": "http://b",
               "RESILIENCE_ALLOW_DESTRUCTIVE": "true"}
        with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(RuntimeError, "fenced"):
            Config.from_env()

    @patch("dcn_resilience.integrations._request")
    def test_keystone_catalog_drives_all_nine_read_only_adapters(self, request):
        catalog = [{"type": kind, "endpoints": [{"interface": "internal", "url": f"http://{name}"}]}
                   for name, (kind, _) in SERVICE_PROBES.items()]
        request.side_effect = [(201, {"token": {"project": {"id": "project"}, "catalog": catalog}},
                                {"X-Subject-Token": "token"})] + [(200, {}, {})] * 9
        session = KeystoneSession("http://keystone", "id", "secret")
        session.authenticate()
        adapters = real_catalog(session)
        self.assertEqual(set(adapters), set(SERVICE_PROBES))
        self.assertTrue(all(item.discover("project")["read_only"] for item in adapters.values()))
        with self.assertRaisesRegex(IntegrationError, "fenced"):
            adapters["nova"].execute("evacuate", "server", {})

    @patch("dcn_resilience.integrations._request")
    def test_opa_requires_explicit_allow(self, request):
        request.return_value = (200, {"result": {"allow": False}}, {})
        with self.assertRaisesRegex(IntegrationError, "denied"):
            OPAClient("http://opa").decide({}, "backup.read", {})

    @patch("dcn_resilience.integrations._request")
    def test_readiness_reports_missing_service_and_contract_write_blockers(self, request):
        catalog = [{"type": kind, "endpoints": [{"interface": "internal", "url": f"http://{name}"}]}
                   for name, (kind, _) in SERVICE_PROBES.items() if name != "rgw"]
        request.side_effect = [(201, {"token": {"project": {"id": "project"}, "catalog": catalog}},
                                {"X-Subject-Token": "token"})] + [(200, {}, {})] * 8 + [(200, {}, {})] * 3
        config = Config("integration", ":memory:", {
            "KEYSTONE_AUTH_URL": "http://keystone", "KEYSTONE_APPLICATION_CREDENTIAL_ID": "id",
            "KEYSTONE_APPLICATION_CREDENTIAL_SECRET": "secret", "OPA_URL": "http://opa",
            "TRACK_A_URL": "http://a", "TRACK_B_URL": "http://b"})
        result = integration_readiness(config)
        self.assertFalse(result["ready"])
        self.assertIn("rgw", result["blockers"])
        self.assertIn("track_a_url", result["blockers"])


if __name__ == "__main__":
    unittest.main()
