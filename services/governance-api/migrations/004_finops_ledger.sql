BEGIN;

CREATE TABLE governance_rate_card (
  version text NOT NULL,
  effective_at timestamptz NOT NULL,
  currency text NOT NULL,
  meter text NOT NULL,
  unit text NOT NULL,
  unit_price numeric(38,12) NOT NULL CHECK(unit_price >= 0),
  policy_digest char(64) NOT NULL,
  PRIMARY KEY(version, meter)
);

CREATE TABLE governance_budget_event (
  event_id uuid PRIMARY KEY,
  domain_id text NOT NULL,
  project_id text NOT NULL,
  budget_id uuid NOT NULL,
  period text NOT NULL,
  threshold integer NOT NULL CHECK(threshold > 0),
  spend numeric(38,12) NOT NULL CHECK(spend >= 0),
  amount numeric(38,12) NOT NULL CHECK(amount > 0),
  outbox_id uuid NOT NULL REFERENCES governance_outbox(id),
  created_at timestamptz NOT NULL,
  UNIQUE(budget_id, period, threshold)
);
CREATE INDEX governance_budget_event_scope ON governance_budget_event(project_id, period);

ALTER TABLE governance_budget_event ENABLE ROW LEVEL SECURITY;
CREATE POLICY governance_budget_event_project ON governance_budget_event
  USING (project_id = current_setting('dcn.project_id', true));

CREATE OR REPLACE FUNCTION governance_reject_immutable_change()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'governance FinOps ledger is append-only';
END;
$$;

CREATE TRIGGER governance_usage_raw_immutable
BEFORE UPDATE OR DELETE ON governance_usage_raw
FOR EACH ROW EXECUTE FUNCTION governance_reject_immutable_change();
CREATE TRIGGER governance_cost_ledger_immutable
BEFORE UPDATE OR DELETE ON governance_cost_ledger
FOR EACH ROW EXECUTE FUNCTION governance_reject_immutable_change();
CREATE TRIGGER governance_rate_card_immutable
BEFORE UPDATE OR DELETE ON governance_rate_card
FOR EACH ROW EXECUTE FUNCTION governance_reject_immutable_change();

INSERT INTO governance_schema_version(version) VALUES (4);
COMMIT;
