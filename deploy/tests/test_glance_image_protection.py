#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).with_name("glance_image_protection.py")
if not MODULE_PATH.exists():
    MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "glance_image_protection.py"
SPEC = importlib.util.spec_from_file_location("glance_image_protection", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ImageProtectionTest(unittest.TestCase):
    def setUp(self):
        self.details = {
            "public-1": {"id": "public-1", "visibility": "public", "protected": False},
            "amphora-1": {"id": "amphora-1", "visibility": "private", "protected": False,
                          "properties": {"os_hidden": True}},
        }
        self.calls = []

    def command(self, *args):
        self.calls.append(args)
        if args[:2] == ("image", "list"):
            if "--public" in args:
                return json.dumps([{"ID": "public-1", "Visibility": "public", "Tags": []}])
            return json.dumps([{"ID": "amphora-1", "Visibility": "private", "Tags": ["amphora"]}])
        if args[:2] == ("image", "show"):
            return json.dumps(self.details[args[2]])
        if args[:3] == ("image", "set", "--protected"):
            self.details[args[3]]["protected"] = True
            return ""
        raise AssertionError(args)

    def test_apply_protects_public_and_hidden_amphora(self):
        with mock.patch.object(MODULE, "run_command", side_effect=self.command):
            MODULE.reconcile("apply")
        self.assertTrue(self.details["public-1"]["protected"])
        self.assertTrue(self.details["amphora-1"]["protected"])

    def test_verify_rejects_unprotected_image(self):
        with mock.patch.object(MODULE, "run_command", side_effect=self.command):
            with self.assertRaisesRegex(RuntimeError, "not protected"):
                MODULE.reconcile("verify")

    def test_amphora_must_remain_hidden(self):
        self.details["amphora-1"]["properties"]["os_hidden"] = False
        with mock.patch.object(MODULE, "run_command", side_effect=self.command):
            with self.assertRaisesRegex(RuntimeError, "not hidden"):
                MODULE.reconcile("apply")


if __name__ == "__main__":
    unittest.main()
