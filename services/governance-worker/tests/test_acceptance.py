import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from governance_worker import acceptance


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"{}"


class AcceptanceTransportTests(unittest.TestCase):
    @patch.object(acceptance.time, "sleep")
    @patch.object(acceptance, "call")
    def test_metric_visibility_is_bounded_before_rating_reset(self, call, sleep):
        call.side_effect = [(200, [["measure"]]), (200, []),
                            (200, [["measure"]]), (200, [["measure"]])]
        acceptance.wait_for_metric_measures(["metric-a", "metric-b"], "token",
                                            attempts=3, delay=5)
        self.assertEqual(call.call_count, 4)
        sleep.assert_called_once_with(5)

    @patch.object(acceptance.time, "sleep")
    @patch.object(acceptance, "call", return_value=(200, []))
    def test_metric_visibility_fails_after_bound(self, call, sleep):
        with self.assertRaisesRegex(RuntimeError, "did not become visible"):
            acceptance.wait_for_metric_measures(["metric"], "token", attempts=3, delay=5)
        self.assertEqual(call.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_checkpoint_starts_the_half_open_interval_containing_measure(self):
        measure = datetime(2026, 8, 17, 7, 0, tzinfo=UTC)
        checkpoint = acceptance.checkpoint_for_measure(measure)
        self.assertEqual(checkpoint, measure)
        self.assertLessEqual(checkpoint, measure)
        self.assertLess(measure, checkpoint + timedelta(hours=1))

    def test_measure_interval_is_older_than_cloudkitty_wait_window(self):
        now = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
        measure = acceptance.eligible_measure_time(now)
        checkpoint = acceptance.checkpoint_for_measure(measure)
        interval_end = checkpoint + timedelta(hours=1)
        self.assertLessEqual(interval_end, now - timedelta(hours=1))

    @patch.object(acceptance.time, "sleep")
    @patch.object(acceptance, "urlopen")
    def test_call_retries_transient_transport_with_a_fixed_bound(self, urlopen, sleep):
        urlopen.side_effect = [URLError("route"), TimeoutError("timeout"), _Response()]

        status, body = acceptance.call("http://service/v1", "token")

        self.assertEqual((status, body), (200, {}))
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(acceptance.time, "sleep")
    @patch.object(acceptance, "urlopen", side_effect=URLError("route"))
    def test_call_stops_after_six_transport_failures(self, urlopen, sleep):
        with self.assertRaises(URLError):
            acceptance.call("http://service/v1", "token")
        self.assertEqual(urlopen.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    @patch.object(acceptance.time, "sleep")
    @patch.object(acceptance, "application_credential_token")
    def test_identity_retries_transient_transport(self, token, sleep):
        token.side_effect = [URLError("route"), "scoped-token"]
        with patch.dict(os.environ, {
                "GOVERNANCE_KEYSTONE_URL": "http://keystone",
                "GOVERNANCE_APPLICATION_CREDENTIAL_ID": "id",
                "GOVERNANCE_APPLICATION_CREDENTIAL_SECRET": "secret",
                "GOVERNANCE_KEYSTONE_PROJECT_ID": "project"}):
            self.assertEqual(acceptance.identity(), ("scoped-token", "project"))
        self.assertEqual(sleep.call_count, 1)


class AcceptanceCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.state = Path(self.tempdir.name) / "state.json"
        self.state.write_text(json.dumps({
            "resource_id": "resource", "budget_id": "budget", "budget_revision": 3
        }), encoding="utf-8")
        self.state_patch = patch.object(acceptance, "STATE", self.state)
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.tempdir.cleanup()

    @patch.object(acceptance, "require_absent")
    @patch.object(acceptance, "identity", return_value=("token", "project"))
    @patch.object(acceptance, "call")
    def test_cleanup_is_idempotent_only_for_not_found(self, call, _identity, absent):
        not_found = HTTPError("http://service", 404, "not found", {}, None)
        call.side_effect = [not_found, not_found]
        with patch.dict(os.environ, {"GOVERNANCE_GNOCCHI_URL": "http://gnocchi"}):
            acceptance.cleanup()
        self.assertFalse(self.state.exists())
        self.assertEqual(absent.call_count, 2)

    @patch.object(acceptance, "identity", return_value=("token", "project"))
    @patch.object(acceptance, "call")
    def test_cleanup_does_not_hide_other_http_errors(self, call, _identity):
        call.side_effect = HTTPError("http://service", 503, "unavailable", {}, None)
        with patch.dict(os.environ, {"GOVERNANCE_GNOCCHI_URL": "http://gnocchi"}):
            with self.assertRaises(HTTPError):
                acceptance.cleanup()
        self.assertTrue(self.state.exists())


if __name__ == "__main__":
    unittest.main()
