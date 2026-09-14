import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


class OVNLocalPVPlacementTest(unittest.TestCase):
    def test_raft_databases_remain_eligible_for_retained_local_volumes(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/ovn.yaml").read_text())
        labels = values["labels"]
        volumes = values["volume"]

        for component in ("ovn_ovsdb_nb", "ovn_ovsdb_sb"):
            self.assertEqual("openvswitch", labels[component]["node_selector_key"])
            self.assertEqual("enabled", labels[component]["node_selector_value"])
            self.assertEqual("/etc/ovn", volumes[component]["path"])
        self.assertEqual(
            "openstack-control-plane",
            labels["ovn_northd"]["node_selector_key"],
        )

    def test_raft_runtime_uses_the_persistent_volume_directory(self):
        for component in ("nb", "sb"):
            template = (
                ROOT
                / f"helm/openstack-helm/ovn/templates/statefulset-ovsdb-{component}.yaml"
            ).read_text()
            self.assertIn("- name: OVN_DBDIR", template)
            self.assertIn(
                f"Values.volume.ovn_ovsdb_{component}.path | quote",
                template,
            )


if __name__ == "__main__":
    unittest.main()
