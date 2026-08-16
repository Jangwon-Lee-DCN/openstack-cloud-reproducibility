import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from governance_api.http import Handler
from governance_api.service import GovernanceService
from governance_api.store import Store


class HttpSmokeTest(unittest.TestCase):
    def test_health(self):
        Handler.service = GovernanceService(Store())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"http://127.0.0.1:{server.server_port}/healthz", timeout=2) as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
