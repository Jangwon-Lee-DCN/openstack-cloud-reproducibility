import pathlib
import unittest

import yaml


ROOT = pathlib.Path(__file__).parents[1]


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = yaml.safe_load((ROOT / "config/tenant-service-catalog.yaml").read_text())

    def test_hardware_preview_is_not_ga(self):
        for name in ("baremetal-virtual", "gpu-passthrough"):
            self.assertEqual("preview", self.catalog["services"][name]["status"])
            self.assertEqual("admin", self.catalog["services"][name]["audience"])

    def test_public_ga_services_have_project_audience(self):
        for service in self.catalog["services"].values():
            if service["status"] == "ga":
                self.assertEqual("project", service["audience"])

    def test_horizon_catalog_app_is_registered_for_template_discovery(self):
        enabled = (
            ROOT.parent
            / "images/horizon-complete/enabled/_1380_dcn_service_catalog.py"
        ).read_text()
        self.assertIn(
            'ADD_INSTALLED_APPS = ["openstack_dashboard.service_catalog"]',
            enabled,
        )
