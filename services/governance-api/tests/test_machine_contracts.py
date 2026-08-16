import json
import hashlib
import pathlib
import unittest
from dataclasses import replace

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from governance_api.operation import FakeOperationClient, STATES
from governance_api.security import RequestContext
from governance_api.service import GovernanceService
from governance_api.store import Store


ROOT = pathlib.Path(__file__).parents[3]
TRACK_A_SCHEMA = ROOT / "deploy/tests/governance/track-a-operation-v1alpha1.json"
TRACK_B_SCHEMA = pathlib.Path(__file__).parents[1] / "contracts/track-b/track-b.event.v1alpha1.schema.json"


class MachineContractTest(unittest.TestCase):
    def validator(self, path):
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        return schema, Draft202012Validator(schema, format_checker=FormatChecker())

    def test_track_a_consumer_matches_canonical_required_fields_and_states(self):
        self.assertEqual(hashlib.sha256(TRACK_A_SCHEMA.read_bytes()).hexdigest(),
                         "592938cfdafea57842e1fe330668a71caef886eb6c6e707ade45a10c9004080d")
        schema, validator = self.validator(TRACK_A_SCHEMA)
        expected_states = {"REQUESTED", "VALIDATING", "SCHEDULED", "RUNNING",
                           "ROLLING_BACK", "SUCCEEDED", "FAILED", "CANCELLED"}
        self.assertEqual(set(schema["properties"]["state"]["enum"]), expected_states)
        self.assertEqual(STATES, expected_states)
        operation = FakeOperationClient().create(
            action="budget.create", idempotency_key="contract-key", request_id="req-contract",
            project_id="11111111-1111-1111-1111-111111111111", target_type="budget")
        validator.validate(operation.as_contract())
        with self.assertRaises(ValidationError):
            validator.validate(replace(operation, state="requested").as_contract())
        self.assertFalse(schema["additionalProperties"])

    def test_track_b_real_producer_has_no_schema_drift(self):
        schema, validator = self.validator(TRACK_B_SCHEMA)
        store = Store()
        service = GovernanceService(store)
        ctx = RequestContext("domain", "project", "actor")
        service.create_budget(ctx, {"amount": "100"}, key="event-key", request_id="req-event")
        payload = Store.decode(store.connection.execute("SELECT payload FROM outbox").fetchone()[0])
        validator.validate(payload)
        self.assertEqual(payload["contract_version"], "track-b.event.v1alpha1")
        drifted = {**payload, "undeclared": True}
        with self.assertRaises(ValidationError):
            validator.validate(drifted)
        self.assertFalse(schema["additionalProperties"])
        self.assertTrue(schema["properties"]["payload"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
