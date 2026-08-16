ALTER TABLE operations ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS operation_transitions (
 project_id uuid NOT NULL,
 operation_id uuid NOT NULL REFERENCES operations(id),
 idempotency_key varchar(255) NOT NULL,
 fingerprint char(64) NOT NULL,
 resulting_revision integer NOT NULL,
 response_json jsonb NOT NULL,
 created_at timestamptz NOT NULL,
 PRIMARY KEY(project_id,operation_id,idempotency_key));
CREATE INDEX IF NOT EXISTS operation_transitions_revision_idx
 ON operation_transitions(operation_id,resulting_revision);
