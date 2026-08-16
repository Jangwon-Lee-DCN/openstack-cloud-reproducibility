import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "tools" / "provision_development_identity.py"
SPEC = importlib.util.spec_from_file_location("provision_development_identity", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProvisionIdentityTest(unittest.TestCase):
    def test_rotation_gets_replacement_token_after_deleting_old_credential(self):
        events = []

        def fake_call(url, token="", method="GET", body=None):
            events.append((method, url, token))
            if method == "GET":
                return {}, {"application_credentials": [
                    {"id": "old-id", "name": "governance-development"}
                ]}
            if method == "POST":
                return {}, {"application_credential": {"id": "new-id", "secret": "not-logged"}}
            return {}, {}

        def fake_password_token(*_args):
            events.append(("TOKEN", "password", ""))
            return "replacement-token", {}

        with patch.object(MODULE, "call", side_effect=fake_call), patch.object(
            MODULE, "password_token", side_effect=fake_password_token
        ):
            result = MODULE.rotate_application_credential(
                "http://keystone/v3", "admin-token", {"id": "user-id", "name": "user"},
                "password", {"name": "project"}, "Default"
            )

        self.assertEqual(result["id"], "new-id")
        self.assertEqual([event[0] for event in events], ["GET", "DELETE", "TOKEN", "POST"])
        self.assertEqual(events[-1][2], "replacement-token")
