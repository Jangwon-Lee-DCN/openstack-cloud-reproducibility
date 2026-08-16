BEGIN;

CREATE TABLE governance_canonical_event (
  event_id uuid PRIMARY KEY,
  domain_id text NOT NULL,
  project_id text NOT NULL,
  idempotency_key text NOT NULL CHECK(length(idempotency_key) BETWEEN 8 AND 255),
  request_hash char(64) NOT NULL,
  status text NOT NULL CHECK(status IN ('accepted')),
  body jsonb NOT NULL,
  received_at timestamptz NOT NULL,
  UNIQUE(project_id, idempotency_key)
);
CREATE INDEX governance_canonical_event_scope
  ON governance_canonical_event(project_id, status, received_at, event_id);

ALTER TABLE governance_canonical_event ENABLE ROW LEVEL SECURITY;
CREATE POLICY governance_canonical_event_project ON governance_canonical_event
  USING (project_id = current_setting('dcn.project_id', true));

INSERT INTO governance_schema_version(version) VALUES (3);
COMMIT;
