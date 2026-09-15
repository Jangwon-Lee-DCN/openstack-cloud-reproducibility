#!/usr/bin/env python3
import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


class GlanceCapacityTest(unittest.TestCase):
    def test_gpu_runtime_catalog_has_required_capacity(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/glance.yaml").read_text())
        self.assertEqual("pvc", values["storage"])
        self.assertEqual("powerstore-rwo-single-path", values["volume"]["class_name"])
        self.assertEqual("200Gi", values["volume"]["size"])


if __name__ == "__main__":
    unittest.main()
