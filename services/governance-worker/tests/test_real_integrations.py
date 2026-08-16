import os
import unittest
from unittest.mock import patch

from governance_worker.real import GovernanceProviders, IntegrationError, initialize_real_integrations


class RealIntegrationTests(unittest.TestCase):
    def test_requires_development_resource_prefix(self):
        with self.assertRaises(IntegrationError):
            GovernanceProviders("token", "production-")

    def test_missing_credentials_fail_closed_without_network(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(IntegrationError, "GOVERNANCE_POSTGRESQL_HOST"):
                initialize_real_integrations()
