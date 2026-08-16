import unittest

from governance_worker.tags import FakeNativeTagAdapter, TagReconciler
from governance_worker.workflows import WorkflowError


class TagAdapterTest(unittest.TestCase):
    def test_dry_run_and_drift_reconciliation(self):
        adapter = FakeNativeTagAdapter("nova", {"server": (4, {"application": "api", "system/old": "x"})})
        desired = {"application": "other", "dcn.ssu.ac.kr/project-id": "p", "system/old": "fixed"}
        preview = TagReconciler().reconcile(adapter, "server", desired, dry_run=True)
        self.assertTrue(preview.changed)
        self.assertEqual(adapter.revision("server"), 4)
        result = TagReconciler().reconcile(adapter, "server", desired)
        self.assertEqual(result.revision, 5)
        self.assertEqual(adapter.read("server")["application"], "api")
        self.assertEqual(adapter.read("server")["system/old"], "fixed")

    def test_revision_conflict_is_detected(self):
        adapter = FakeNativeTagAdapter("cinder", {"volume": (1, {})})
        with self.assertRaises(WorkflowError):
            adapter.write("volume", {"x": "y"}, 0)


if __name__ == "__main__":
    unittest.main()
