import base64
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("service_credentials", ROOT / "deploy/scripts/render-vpc-service-credentials.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ServiceCredentialsTest(unittest.TestCase):
    def setUp(self):
        self.source = {"data": {"OS_" + key: base64.b64encode(value.encode()).decode() for key, value in {
            "USERNAME": "test-user", "PASSWORD": "private-test-value", "PROJECT_NAME": "test-project",
            "USER_DOMAIN_NAME": "Default", "PROJECT_DOMAIN_NAME": "Default",
            "REGION_NAME": "test-region", "INTERFACE": "public"}.items()}}
        self.ca = (ROOT / "images/keystone-oidc/openstack-public-ca.crt").read_bytes()
        self.ca_secret = {"data": {"ca.crt": base64.b64encode(self.ca).decode()}}

    def test_secure_repeatable_credentials(self):
        result = module.render(self.source, self.ca_secret, "https://identity.example/v3")
        self.assertEqual(result, module.render(self.source, self.ca_secret, "https://identity.example/v3"))
        cloud = yaml.safe_load(base64.b64decode(result["data"]["clouds.yaml"]))["clouds"]["openstack"]
        self.assertIs(cloud["verify"], True)
        self.assertEqual(cloud["endpoint_type"], "public")
        self.assertNotIn("interface", cloud)
        self.assertNotIn("cacert", cloud)
        self.assertEqual(cloud["auth"]["password"], "private-test-value")
        self.assertEqual(base64.b64decode(result["data"]["cacert"]), self.ca)

    def test_reject_insecure_or_ambiguous_endpoint(self):
        for url in ("http://identity.example/v3", "https://user:password@identity.example/v3",
                    "https://identity.example/v3?token=x", "https://identity.example/v2"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.render(self.source, self.ca_secret, url)

    def test_reject_invalid_ca(self):
        with self.assertRaises(Exception):
            module.render(self.source, {"data": {"ca.crt": "aW52YWxpZA=="}}, "https://identity.example/v3")

    def test_reject_missing_identity(self):
        self.source["data"].pop("OS_PASSWORD")
        with self.assertRaises(KeyError):
            module.render(self.source, self.ca_secret, "https://identity.example/v3")

    def test_cli_check_never_emits_credentials(self):
        for url, expected in (("https://identity.example/v3", 0), ("http://identity.example/v3", 1)):
            # Supply only fixture public CA through an inherited pipe, no files.
            read_fd, write_fd = os.pipe()
            try:
                os.write(write_fd, json.dumps(self.ca_secret).encode())
                os.close(write_fd)
                result = subprocess.run(["python3", str(ROOT / "deploy/scripts/render-vpc-service-credentials.py"),
                    "--ca-secret", f"/dev/fd/{read_fd}", "--identity-url", url, "--check"],
                    input=json.dumps(self.source), capture_output=True, text=True, pass_fds=(read_fd,), timeout=10)
            finally:
                os.close(read_fd)
            self.assertEqual(result.returncode, expected)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("private-test-value", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
