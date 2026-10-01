import os
import pathlib
import subprocess
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCK = ROOT / "deploy/locks/vpc-policy-images.yaml"
RENDERER = ROOT / "deploy/scripts/render-vpc-policy-plane.py"
SOURCE = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: vpc-control-plane-controller-manager}
spec:
  template:
    spec:
      containers:
        - {name: manager, image: placeholder}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: vpc-facade}
spec:
  template:
    spec:
      containers:
        - {name: apiserver, image: placeholder}
"""


class VPCPolicyPlaneRollbackTest(unittest.TestCase):
    def setUp(self):
        self.lock = yaml.safe_load(LOCK.read_text())["spec"]

    def render(self, override=None):
        env = os.environ.copy()
        if override is not None:
            env["VPC_CONTROLLER_IMAGE_OVERRIDE"] = override
        return subprocess.run(
            ["python3", str(RENDERER), str(LOCK)],
            input=SOURCE,
            text=True,
            capture_output=True,
            env=env,
        )

    @staticmethod
    def controller_image(output):
        documents = [item for item in yaml.safe_load_all(output) if item]
        deployment = next(
            item for item in documents
            if item.get("kind") == "Deployment"
            and item["metadata"]["name"] == "vpc-control-plane-controller-manager"
        )
        return deployment["spec"]["template"]["spec"]["containers"][0]["image"]

    def test_default_and_rollback_images_are_locked(self):
        default = self.render()
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(self.controller_image(default.stdout), self.lock["controllerImage"])

        rollback = self.render(self.lock["rollbackControllerImage"])
        self.assertEqual(rollback.returncode, 0, rollback.stderr)
        self.assertEqual(
            self.controller_image(rollback.stdout),
            self.lock["rollbackControllerImage"],
        )

    def test_unlocked_override_is_rejected(self):
        result = self.render("registry.invalid/controller@sha256:" + "0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not an allowed locked image", result.stderr)


if __name__ == "__main__":
    unittest.main()
