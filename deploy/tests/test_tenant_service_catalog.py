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
        dockerfile = (ROOT.parent / "images/horizon-complete/Dockerfile").read_text()
        self.assertIn("chmod 0644 /etc/openstack-dashboard/dcn-service-catalog.yaml", dockerfile)

    def test_instance_type_table_keeps_availability_separate_from_name(self):
        root = ROOT.parent / "images/horizon-complete/service_catalog"
        view = (root / "views.py").read_text()
        template = (root / "templates/service_catalog/index.html").read_text()
        self.assertIn("get_catalog(self.request.user)", view)
        self.assertNotIn('catalog["accelerators"]', view)
        self.assertNotIn('id="dcn-accelerator-catalog"', template)
        self.assertIn("Accelerator guarantee", template)
        self.assertIn("flavor.accelerator.model", template)
        self.assertIn("flavor.accelerator.delivery", template)
        self.assertIn('LOG.exception("Flavor availability lookup failed")', view)
        self.assertIn('data-availability="{{ flavor.availability }}"', template)
        self.assertIn("Eligible hosts", template)
        self.assertIn("Checked at", template)
        self.assertIn("flavor.reason", template)

    def test_horizon_reconciler_injects_internal_catalog_endpoint(self):
        reconcile = (ROOT / "scripts/reconcile-full-stack.sh").read_text()
        self.assertIn("FLAVOR_CATALOG_API_URL", reconcile)
        self.assertIn("flavor-catalog.openstack.svc.cluster.local:8080", reconcile)
