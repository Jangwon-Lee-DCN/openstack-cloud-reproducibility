import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[2]


class NovaIscsiConnectorTest(unittest.TestCase):
    def test_nova_compute_mounts_host_iscsi_state(self):
        values = yaml.safe_load((ROOT / "deploy/values/site/nova.yaml").read_text())
        self.assertIs(values["conf"]["enable_iscsi"], True)

    def test_host_role_generates_missing_initiator_identity(self):
        tasks = yaml.safe_load(
            (ROOT / "automation/ansible/roles/host_base/tasks/main.yml").read_text()
        )
        names = {task["name"] for task in tasks}
        self.assertIn("Generate a stable host iSCSI initiator identity", names)
        self.assertIn("Persist the generated host iSCSI initiator identity", names)
        self.assertIn("Enable iSCSI for Cinder attachment", names)


if __name__ == "__main__":
    unittest.main()
