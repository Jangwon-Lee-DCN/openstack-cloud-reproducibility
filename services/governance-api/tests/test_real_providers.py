import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from governance_api.providers import KeystoneIdentity, OpaAuthorizer, ProviderError, ProviderRegistry


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        if self.path == "/v3/auth/tokens" and self.headers.get("X-Auth-Token") == "valid":
            body = b'{"token":{"project":{"id":"project-a","domain":{"id":"domain-a"}},"user":{"id":"user-a"},"roles":[{"name":"member"}]}}'
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else: self.send_error(401)
    def do_POST(self):
        body = b'{"result":{"allow":true}}'
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


class RealProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
    @classmethod
    def tearDownClass(cls): cls.server.shutdown()

    def test_keystone_project_scope_and_opa_allow(self):
        self.assertEqual(KeystoneIdentity(self.url).validate("valid", "project-a")["project_id"], "project-a")
        with self.assertRaises(ProviderError): KeystoneIdentity(self.url).validate("valid", "project-b")
        self.assertTrue(OpaAuthorizer(self.url, "governance/allow").authorize({"project_id": "project-a"}))

    def test_registry_fails_closed_when_required_provider_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            registry = ProviderRegistry()
            self.assertFalse(registry.ready())
            self.assertTrue(set(ProviderRegistry.REQUIRED).issubset({s.name for s in registry.statuses()}))
