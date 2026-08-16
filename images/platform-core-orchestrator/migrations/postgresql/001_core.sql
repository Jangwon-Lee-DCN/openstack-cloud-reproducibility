BEGIN;
CREATE TABLE operations (
 id uuid PRIMARY KEY, project_id uuid NOT NULL, region_id text NOT NULL,
 action text NOT NULL, target_type text NOT NULL, target_id uuid,
 fingerprint char(64) NOT NULL, idempotency_key varchar(255) NOT NULL,
 state text NOT NULL, progress smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
 current_step text, error_json jsonb, correlation_id uuid NOT NULL,
 created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL,
 lease_owner text, lease_expires_at timestamptz, attempt integer NOT NULL DEFAULT 0,
 next_attempt_at timestamptz, checkpoint_json jsonb, request_json jsonb NOT NULL DEFAULT '{}'::jsonb,
 UNIQUE(project_id,idempotency_key));
CREATE INDEX operations_runnable_idx ON operations(state,next_attempt_at,lease_expires_at,created_at);
CREATE TABLE operation_events (id bigserial PRIMARY KEY, operation_id uuid NOT NULL REFERENCES operations(id), event_type text NOT NULL, payload_json jsonb NOT NULL, created_at timestamptz NOT NULL);
CREATE TABLE outbox (id bigserial PRIMARY KEY, topic text NOT NULL, aggregate_id uuid NOT NULL, payload_json jsonb NOT NULL, created_at timestamptz NOT NULL, published_at timestamptz);
CREATE INDEX outbox_unpublished_idx ON outbox(id) WHERE published_at IS NULL;
CREATE TABLE inbound_events (event_id text PRIMARY KEY, source text NOT NULL, received_at timestamptz NOT NULL);
CREATE TABLE dead_letters (operation_id uuid PRIMARY KEY REFERENCES operations(id), reason text NOT NULL, checkpoint_json jsonb NOT NULL, failed_at timestamptz NOT NULL);
CREATE TABLE preflights (
 id uuid PRIMARY KEY, project_id uuid NOT NULL, kind text NOT NULL,
 fingerprint char(64) NOT NULL, decision text NOT NULL, result_json jsonb NOT NULL,
 expires_at timestamptz NOT NULL);
CREATE TABLE launch_templates (
 id uuid PRIMARY KEY, project_id uuid NOT NULL, name text NOT NULL,
 description text NOT NULL DEFAULT '', default_version integer NOT NULL DEFAULT 1,
 deletion_protected boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL,
 UNIQUE(project_id,name));
CREATE TABLE launch_template_versions (
 template_id uuid NOT NULL REFERENCES launch_templates(id), version integer NOT NULL,
 spec_json jsonb NOT NULL, checksum char(64) NOT NULL, created_by uuid NOT NULL,
 created_at timestamptz NOT NULL, PRIMARY KEY(template_id,version));
CREATE TABLE auto_scaling_groups (
 id uuid PRIMARY KEY, project_id uuid NOT NULL, region_id text NOT NULL,
 template_id uuid NOT NULL REFERENCES launch_templates(id), template_version integer NOT NULL,
 min_size integer NOT NULL, desired integer NOT NULL, max_size integer NOT NULL,
 subnet_ids_json jsonb NOT NULL, cooldown_seconds integer NOT NULL,
 state text NOT NULL, deletion_protected boolean NOT NULL DEFAULT false,
 last_scaled_at timestamptz, created_at timestamptz NOT NULL,
 CHECK (0 <= min_size AND min_size <= desired AND desired <= max_size),
 FOREIGN KEY(template_id,template_version) REFERENCES launch_template_versions(template_id,version));
CREATE TABLE scaling_events (
 event_id text PRIMARY KEY, group_id uuid NOT NULL REFERENCES auto_scaling_groups(id),
 adjustment integer NOT NULL, accepted boolean NOT NULL, reason text NOT NULL,
 created_at timestamptz NOT NULL);
CREATE TABLE asg_members (
 id uuid PRIMARY KEY, group_id uuid NOT NULL REFERENCES auto_scaling_groups(id),
 provider_id text NOT NULL, state text NOT NULL, created_at timestamptz NOT NULL,
 UNIQUE(group_id,provider_id));
CREATE TABLE resource_protection (
 project_id uuid NOT NULL, resource_type text NOT NULL, resource_id uuid NOT NULL,
 protected boolean NOT NULL, reason text, updated_by uuid NOT NULL,
 updated_at timestamptz NOT NULL, PRIMARY KEY(project_id,resource_type,resource_id));
CREATE TABLE recycle_bin (
 id uuid PRIMARY KEY, project_id uuid NOT NULL, resource_type text NOT NULL,
 resource_id uuid NOT NULL, provider_ids_json jsonb NOT NULL, deleted_by uuid NOT NULL,
 deleted_at timestamptz NOT NULL, purge_after timestamptz NOT NULL,
 restore_capability text NOT NULL, dependency_json jsonb NOT NULL, state text NOT NULL);
COMMIT;
