import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[2]


class FlavorCatalogClientTest(unittest.TestCase):
    def test_internal_get_retries_are_bounded_and_cover_read_failures(self):
        source_path = ROOT / "images/horizon-complete/service_catalog/flavor_api.py"
        spec = importlib.util.spec_from_file_location("dcn_flavor_api", source_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        retry = module._SESSION.get_adapter("http://").max_retries
        self.assertEqual(2, retry.total)
        self.assertEqual(2, retry.connect)
        self.assertEqual(2, retry.read)
        self.assertEqual(2, retry.status)
        self.assertEqual({429, 502, 503, 504}, set(retry.status_forcelist))
        self.assertEqual(frozenset({"GET"}), retry.allowed_methods)

        source = source_path.read_text()
        self.assertIn("timeout=(3.05, 10)", source)
        self.assertIn("response.raise_for_status()", source)


if __name__ == "__main__":
    unittest.main()
