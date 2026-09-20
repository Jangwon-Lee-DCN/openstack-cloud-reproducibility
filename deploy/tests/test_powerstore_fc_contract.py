import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]


class PowerStoreFCContractTests(unittest.TestCase):
    def test_fc_backend_is_opt_in_and_keeps_iscsi(self):
        values = yaml.safe_load(
            (ROOT / "deploy/values/features/cinder-powerstore-fc.yaml").read_text()
        )
        self.assertEqual(
            "rbd1,powerstore_fc", values["conf"]["cinder"]["DEFAULT"]["enabled_backends"]
        )
        backend = values["conf"]["backends"]["powerstore_fc"]
        self.assertEqual("FC", backend["storage_protocol"])
        self.assertEqual("POWERSTORE_FC", backend["volume_backend_name"])
        self.assertEqual(
            "POWERSTORE_FC",
            values["bootstrap"]["volume_types"]["powerstore-fc"]["volume_backend_name"],
        )

    def test_reconciler_requires_explicit_fc_switch(self):
        script = (ROOT / "deploy/scripts/reconcile-full-stack.sh").read_text()
        self.assertIn("ENABLE_POWERSTORE_FC=${ENABLE_POWERSTORE_FC:-0}", script)
        self.assertIn('"$ENABLE_POWERSTORE_FC" == "1"', script)


if __name__ == "__main__":
    unittest.main()
