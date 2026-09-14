from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class OpenStackExporterReleaseTests(unittest.TestCase):
    def test_install_uses_release_locked_patched_chart(self):
        install = (ROOT / "deploy/monitoring/scripts/install.sh").read_text()
        self.assertIn(
            "helm/packages/patched/prometheus-openstack-exporter-2026.1.0.tgz",
            install,
        )
        self.assertNotIn(
            "helm/packages/upstream/prometheus-openstack-exporter-2026.1.0.tgz",
            install,
        )

    def test_render_uses_control_pool_and_declared_tls_policy(self):
        rendered = subprocess.run(
            [
                "helm",
                "template",
                "prometheus-openstack-exporter",
                str(
                    ROOT
                    / "helm/packages/patched/"
                    "prometheus-openstack-exporter-2026.1.0.tgz"
                ),
                "-f",
                str(ROOT / "deploy/monitoring/values/openstack-exporter.yaml"),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn('openstack-control-plane: "enabled"', rendered)
        self.assertIn("verify: false", rendered)
        self.assertNotIn('openstack-compute-node: "enabled"', rendered)


if __name__ == "__main__":
    unittest.main()
