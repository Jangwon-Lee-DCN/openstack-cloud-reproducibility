from pathlib import Path
import json
import sys
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[2]


class PreviewFlavorAccessContractTests(unittest.TestCase):
    def test_access_reconciliation_uses_project_independent_nova_url(self):
        script = (
            ROOT / "deploy/scripts/reconcile-preview-service-catalog.sh"
        ).read_text()

        self.assertIn('r"/v2\\.1(?:/.*)?$", "/v2.1"', script)
        self.assertIn(
            'access_url = f"{api_root}/flavors/{flavor_id}/os-flavor-access"',
            script,
        )
        self.assertIn(
            'action_url = f"{api_root}/flavors/{flavor_id}/action"', script
        )
        self.assertIn("urllib.request.Request(access_url, headers=headers)", script)
        self.assertIn("action_url,\n        data=json.dumps", script)
        self.assertIn('"removeTenantAccess"', script)
        self.assertIn("urllib.request", script)
        self.assertNotIn("flavor unset --project", script)

    def test_access_reconciliation_executes_distinct_get_and_action_urls(self):
        script = (
            ROOT / "deploy/scripts/reconcile-preview-service-catalog.sh"
        ).read_text()
        code = script.split("<<'PY'\n", 2)[2].split("\nPY\nunset token", 1)[0]
        requests = []
        responses = iter(
            [
                {"flavor_access": [{"tenant_id": "admin"}, {"tenant_id": "stale"}]},
                {},
                {"flavor_access": [{"tenant_id": "admin"}]},
            ]
        )

        class Response:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return json.dumps(self.payload).encode()

        def fake_urlopen(request, timeout):
            self.assertEqual(60, timeout)
            requests.append(request)
            return Response(next(responses))

        old_argv = sys.argv
        old_urlopen = urllib.request.urlopen
        try:
            sys.argv = [
                "reconcile",
                "http://nova:8774/v2.1/%(project_id)s",
                "secret-token",
                "flavor-id",
                "admin",
            ]
            urllib.request.urlopen = fake_urlopen
            exec(compile(code, "reconcile-flavor-access", "exec"), {})
        finally:
            sys.argv = old_argv
            urllib.request.urlopen = old_urlopen

        self.assertEqual(
            "http://nova:8774/v2.1/flavors/flavor-id/os-flavor-access",
            requests[0].full_url,
        )
        self.assertEqual("GET", requests[0].get_method())
        self.assertEqual(
            "http://nova:8774/v2.1/flavors/flavor-id/action",
            requests[1].full_url,
        )
        self.assertEqual("POST", requests[1].get_method())
        self.assertEqual(
            {"removeTenantAccess": {"tenant": "stale"}},
            json.loads(requests[1].data),
        )
        self.assertEqual("GET", requests[2].get_method())


if __name__ == "__main__":
    unittest.main()
