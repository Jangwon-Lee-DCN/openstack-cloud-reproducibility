"""PostgreSQL repository statements used by the production repository adapter.

Kept parameter-style neutral at the interface boundary; a psycopg adapter binds
named parameters. SQLite development code must never be promoted as the HA
repository implementation.
"""

CLAIM_OPERATION = """
WITH candidate AS (
 SELECT id FROM operations
 WHERE state = ANY(%(states)s)
   AND (next_attempt_at IS NULL OR next_attempt_at <= %(now)s)
   AND (lease_expires_at IS NULL OR lease_expires_at <= %(now)s)
 ORDER BY created_at
 FOR UPDATE SKIP LOCKED
 LIMIT 1
)
UPDATE operations AS operation
SET lease_owner=%(worker_id)s, lease_expires_at=%(lease_until)s,
    attempt=attempt+1, updated_at=%(now)s
FROM candidate
WHERE operation.id=candidate.id
RETURNING operation.*
"""

PUBLISH_OUTBOX = """
SELECT id,topic,aggregate_id,payload_json FROM outbox
WHERE published_at IS NULL ORDER BY id FOR UPDATE SKIP LOCKED LIMIT %(batch_size)s
"""
