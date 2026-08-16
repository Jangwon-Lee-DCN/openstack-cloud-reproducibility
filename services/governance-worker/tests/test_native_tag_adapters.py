import unittest

from governance_worker.native_tags import CollectionTagAdapter, MetadataTagAdapter, decode_tags, encode_tags


class Client:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def request(self, path, **kwargs):
        self.calls.append((path, kwargs)); return 200, self.responses.pop(0) if self.responses else {}


class NativeAdaptersTest(unittest.TestCase):
    def test_metadata_adapter_uses_project_scoped_service_api(self):
        client = Client([{"metadata": {"team": "dcn"}}, {}])
        adapter = MetadataTagAdapter(client, "project", "nova")
        self.assertEqual(adapter.read("server"), {"team": "dcn"})
        self.assertEqual(adapter.write("server", {"team": "cloud"}, 2), 3)
        self.assertEqual(client.calls[1][1]["body"], {"metadata": {"team": "cloud"}})

    def test_neutron_collection_and_tag_encoding(self):
        self.assertEqual(decode_tags(encode_tags({"b": "2", "a": "1"})), {"a": "1", "b": "2"})
        client = Client([{"tags": ["team=dcn"]}, {}])
        adapter = CollectionTagAdapter(client, "neutron", "networks")
        self.assertEqual(adapter.read("network"), {"team": "dcn"})
        adapter.write("network", {"team": "cloud"}, 1)
        self.assertEqual(client.calls[1][1]["body"], {"tags": ["team=cloud"]})
