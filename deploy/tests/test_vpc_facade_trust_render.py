import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("vpc_render", ROOT / "deploy/scripts/render-vpc-policy-plane.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FacadeTrustRenderTest(unittest.TestCase):
    def setUp(self):
        self.container = {"name": "apiserver", "env": [{"name": "KEEP", "value": "unchanged"}]}
        self.pod = {"containers": [self.container], "volumes": [{"name": "keep", "emptyDir": {}}]}

    def test_readonly_secret_and_idempotence(self):
        module.ensure_facade_trust(self.pod, self.container)
        first = copy.deepcopy(self.pod)
        module.ensure_facade_trust(self.pod, self.container)
        self.assertEqual(self.pod, first)
        self.assertEqual(self.container["env"][0], {"name": "KEEP", "value": "unchanged"})
        self.assertTrue(self.container["volumeMounts"][0]["readOnly"])
        self.assertEqual(self.pod["volumes"][1]["secret"]["items"], [{"key": "ca.crt", "path": "ca.crt"}])

    def test_foreign_mount_rejected(self):
        self.container["volumeMounts"] = [{"name": "other", "mountPath": "/etc/vpc-facade/openstack-ca"}]
        with self.assertRaises(ValueError):
            module.ensure_facade_trust(self.pod, self.container)

    def test_kubernetes_default_mode_can_be_omitted(self):
        module.ensure_facade_trust(self.pod, self.container)
        del self.pod["volumes"][1]["secret"]["defaultMode"]
        module.ensure_facade_trust(self.pod, self.container)
        self.pod["volumes"][1]["secret"]["defaultMode"] = 0o777
        with self.assertRaises(ValueError):
            module.ensure_facade_trust(self.pod, self.container)

    def test_conflicting_env_or_volume_rejected(self):
        for target, key, value in ((self.container, "env", {"name": "SSL_CERT_FILE", "value": "/other"}),
                                   (self.pod, "volumes", {"name": "openstack-public-ca", "emptyDir": {}})):
            with self.subTest(key=key):
                pod, container = copy.deepcopy(self.pod), copy.deepcopy(self.container)
                (container if target is self.container else pod)[key].append(value)
                with self.assertRaises(ValueError):
                    module.ensure_facade_trust(pod, container)

    def test_duplicate_env_rejected(self):
        env = {"name": "SSL_CERT_FILE", "value": "/etc/vpc-facade/openstack-ca/ca.crt"}
        self.container["env"].extend([env, env.copy()])
        with self.assertRaises(ValueError):
            module.ensure_facade_trust(self.pod, self.container)
