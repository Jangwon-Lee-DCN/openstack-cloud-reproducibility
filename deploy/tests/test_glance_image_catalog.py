#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

PATH = pathlib.Path(__file__).with_name("glance_image_catalog.py")
if not PATH.exists():
    PATH = pathlib.Path(__file__).parents[1] / "scripts" / "glance_image_catalog.py"
SPEC = importlib.util.spec_from_file_location("catalog", PATH)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class CatalogTest(unittest.TestCase):
    def catalog(self, hidden=False, workload="general"):
        return {"schema": "dcn.glance.catalog/v1", "images": [{
            "name": "ubuntu", "visibility": "public", "hidden": hidden,
            "protected": True, "class": "platform", "workload_type": workload,
            "support_status": "recommended", "os_distro": "ubuntu", "os_version": "24.04"}]}

    def test_rejects_visible_service_image(self):
        data = self.catalog(False, "capi")
        with tempfile.NamedTemporaryFile("w") as stream:
            import yaml
            yaml.safe_dump(data, stream); stream.flush()
            with self.assertRaisesRegex(ValueError, "service image must be hidden"):
                MOD.load_catalog(stream.name)

    def test_reconcile_detects_unprotected(self):
        responses = [json.dumps([{"ID":"1","Name":"ubuntu","Checksum":"a"}]), "[]",
                     json.dumps({"id":"1","visibility":"public","protected":False,
                                 "properties":{"os_hidden":False},"tags":[]})]
        with mock.patch.object(MOD, "command", side_effect=responses):
            self.assertEqual(1, MOD.reconcile(self.catalog(), apply=False))

    def test_apply_sets_metadata_hidden_and_protection(self):
        data = self.catalog(True, "capi")
        data["images"][0]["class"] = "service"
        responses = [json.dumps([{"ID":"1","Name":"ubuntu","Checksum":"a"}]), "[]",
                     json.dumps({"id":"1","visibility":"public","protected":False,
                                 "properties":{"os_hidden":False},"tags":[]})]
        with mock.patch.object(MOD, "command", side_effect=responses + [""] * 4) as run:
            self.assertEqual(0, MOD.reconcile(data, apply=True))
            calls = [call.args for call in run.call_args_list]
            self.assertTrue(any("--hidden" in call for call in calls))
            self.assertTrue(any("--protected" in call for call in calls))


if __name__ == "__main__": unittest.main()
