import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[2]
TEMPLATE = ROOT / "images/horizon-complete/image_catalog/index_split.html"


class HorizonImageCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_detail_panel_keeps_metadata_out_of_image_names(self):
        self.assertIn('id="image-inspector"', self.source)
        self.assertIn("properties.dcn_support_status", self.source)
        self.assertIn("properties.kube_version", self.source)
        self.assertNotIn("— CAPI Kubernetes", self.source)

    def test_linked_resources_are_project_scoped_horizon_apis(self):
        self.assertIn("api/nova/servers/", self.source)
        self.assertIn("api/container_infra/clusters/", self.source)
        self.assertIn("api/container_infra/cluster_templates/", self.source)
        self.assertIn("api/lbaas/loadbalancers/", self.source)
        self.assertIn('id = \'image-linked-resources\'', self.source)

    def test_async_failures_are_visible_and_retryable(self):
        self.assertIn("response.headers.get('content-type')", self.source)
        self.assertIn("new AbortController()", self.source)
        self.assertIn('id = \'image-inspector-retry\'', self.source)
        self.assertIn("failure.name === 'AbortError'", self.source)

    def test_statuses_are_simple_badges(self):
        for value in ("recommended", "supported", "deprecated", "end-of-support"):
            self.assertIn(value, self.source)
        self.assertIn("label label-", self.source)


if __name__ == "__main__":
    unittest.main()
