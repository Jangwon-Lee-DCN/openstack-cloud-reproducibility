BEGIN;

CREATE TABLE governance_schema_version (
  version integer PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE governance_resource (
  kind text NOT NULL,
  id uuid NOT NULL,
  domain_id text NOT NULL,
  project_id text NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  body jsonb NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY (kind, id)
);
CREATE INDEX governance_resource_scope ON governance_resource(kind, project_id, updated_at, id);

CREATE TABLE governance_idempotency (
  project_id text NOT NULL,
  action text NOT NULL,
  key text NOT NULL,
  response jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(project_id, action, key)
);

CREATE TABLE governance_outbox (
  id uuid PRIMARY KEY,
  project_id text NOT NULL,
  event_type text NOT NULL,
  dedup_key text NOT NULL,
  payload jsonb NOT NULL,
  status text NOT NULL CHECK(status IN ('pending','leased','retry','delivered','dead')),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts >= 0),
  available_at timestamptz NOT NULL,
  lease_owner text,
  lease_until timestamptz,
  last_error text,
  created_at timestamptz NOT NULL,
  UNIQUE(project_id, dedup_key)
);
CREATE INDEX governance_outbox_ready ON governance_outbox(status, available_at, lease_until);

CREATE TABLE governance_audit_event (
  seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id uuid UNIQUE NOT NULL,
  domain_id text NOT NULL,
  project_id text NOT NULL,
  occurred_at timestamptz NOT NULL,
  body jsonb NOT NULL,
  previous_hash char(64) NOT NULL,
  integrity_hash char(64) UNIQUE NOT NULL
);
CREATE INDEX governance_audit_scope ON governance_audit_event(project_id, seq);

CREATE TABLE governance_telemetry_checkpoint (
  source text NOT NULL,
  project_id text NOT NULL,
  watermark text NOT NULL,
  updated_at timestamptz NOT NULL,
  PRIMARY KEY(source, project_id)
);

CREATE TABLE governance_usage_raw (
  project_id text NOT NULL,
  sample_id text NOT NULL,
  period text NOT NULL,
  meter text NOT NULL,
  quantity numeric(38,12) NOT NULL,
  watermark text NOT NULL,
  received_at timestamptz NOT NULL,
  PRIMARY KEY(project_id, sample_id)
);

CREATE TABLE governance_cost_ledger (
  entry_id uuid PRIMARY KEY,
  project_id text NOT NULL,
  sample_id text NOT NULL,
  period text NOT NULL,
  meter text NOT NULL,
  quantity numeric(38,12) NOT NULL,
  unit_price numeric(38,12) NOT NULL,
  cost numeric(38,12) NOT NULL,
  rate_version text NOT NULL,
  created_at timestamptz NOT NULL,
  UNIQUE(project_id, sample_id)
);

CREATE TABLE governance_replay_nonce (
  consumer_id text NOT NULL,
  nonce text NOT NULL,
  expires_at timestamptz NOT NULL,
  PRIMARY KEY(consumer_id, nonce)
);

INSERT INTO governance_schema_version(version) VALUES (1);
COMMIT;
