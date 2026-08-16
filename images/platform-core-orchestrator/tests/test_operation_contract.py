import json
import os
import tempfile
import unittest
from pathlib import Path

import yaml

from core.service import CoreService, OPERATION_CONTRACT_VERSION
from core.store import Store


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "contracts" / "track-a" / "track-a.operation.v1alpha1.schema.json"
OPENAPI_PATH = ROOT / "images" / "platform-core-orchestrator" / "openapi.yaml"


class OperationContractTest(unittest.TestCase):
    def test_openapi_and_canonical_schema_are_identical(self):
        canonical = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        openapi = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))["components"]["schemas"]["Operation"]
        comparable = {key: canonical[key] for key in ("type", "additionalProperties", "required", "properties")}
        self.assertEqual(comparable, openapi)
        self.assertEqual(OPERATION_CONTRACT_VERSION, canonical["properties"]["contract_version"]["const"])
        self.assertEqual("state", canonical["required"][9])
        self.assertTrue(all(value == value.upper() for value in canonical["properties"]["state"]["enum"]))

    def test_actual_operation_response_has_exact_schema_fields(self):
        fd, path = tempfile.mkstemp(); os.close(fd)
        try:
            service = CoreService(Store(path), b"x" * 32)
            operation, _ = service.create_operation(
                "00000000-0000-0000-0000-000000000001", "seoul-ssu-1",
                "instance.create", "instance", {"network": {}}, "contract-test")
            canonical = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            self.assertEqual(set(canonical["required"]), set(operation))
            self.assertEqual(set(canonical["properties"]), set(operation))
            self.assertEqual(OPERATION_CONTRACT_VERSION, operation["contract_version"])
        finally:
            os.unlink(path)


if __name__ == "__main__": unittest.main()
