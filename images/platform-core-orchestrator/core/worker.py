from datetime import datetime, timedelta, timezone


def iso(value): return value.astimezone(timezone.utc).isoformat()


class DurableWorker:
    def __init__(self, store, worker_id, lease_seconds=30, max_attempts=5):
        self.store, self.worker_id, self.lease_seconds, self.max_attempts = store, worker_id, lease_seconds, max_attempts

    def claim(self, current_time=None):
        current_time = current_time or datetime.now(timezone.utc)
        return self.store.claim_operation(self.worker_id, self.lease_seconds, iso(current_time), iso(current_time + timedelta(seconds=self.lease_seconds)))

    def heartbeat(self, operation_id, current_time=None):
        current_time = current_time or datetime.now(timezone.utc)
        return self.store.heartbeat(operation_id, self.worker_id, iso(current_time), iso(current_time + timedelta(seconds=self.lease_seconds)))

    def save(self, operation_id, state, step, checkpoint, current_time=None, retry_after=None, release=False):
        current_time = current_time or datetime.now(timezone.utc)
        next_attempt = iso(current_time + timedelta(seconds=retry_after)) if retry_after is not None else None
        return self.store.checkpoint(operation_id, self.worker_id, state, step, checkpoint, iso(current_time), next_attempt, release)
