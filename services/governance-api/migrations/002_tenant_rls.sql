BEGIN;

ALTER TABLE governance_resource ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_idempotency ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_cost_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_usage_raw ENABLE ROW LEVEL SECURITY;

CREATE POLICY governance_resource_project ON governance_resource
  USING (project_id = current_setting('dcn.project_id', true));
CREATE POLICY governance_idempotency_project ON governance_idempotency
  USING (project_id = current_setting('dcn.project_id', true));
CREATE POLICY governance_audit_project ON governance_audit_event
  USING (project_id = current_setting('dcn.project_id', true));
CREATE POLICY governance_ledger_project ON governance_cost_ledger
  USING (project_id = current_setting('dcn.project_id', true));
CREATE POLICY governance_raw_usage_project ON governance_usage_raw
  USING (project_id = current_setting('dcn.project_id', true));

INSERT INTO governance_schema_version(version) VALUES (2);
COMMIT;
