import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


class OVNLocalPVPlacementTest(unittest.TestCase):
    def test_raft_databases_remain_eligible_for_retained_local_volumes(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/ovn.yaml").read_text())
        labels = values["labels"]

        for component in ("ovn_ovsdb_nb", "ovn_ovsdb_sb"):
            self.assertEqual("openvswitch", labels[component]["node_selector_key"])
            self.assertEqual("enabled", labels[component]["node_selector_value"])
        self.assertEqual(
            "openstack-control-plane",
            labels["ovn_northd"]["node_selector_key"],
        )


if __name__ == "__main__":
    unittest.main()
