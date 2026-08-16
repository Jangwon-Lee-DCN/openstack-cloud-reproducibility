from datetime import datetime, timedelta, timezone

from .adapters import ProviderError


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

    def execute_once(self, provisioner, current_time=None):
        current_time = current_time or datetime.now(timezone.utc)
        operation = self.claim(current_time)
        if not operation:
            return None
        checkpoint = operation.get("checkpoint") or {}
        if operation["action"] not in {"instance.create", "instance.create.retry"}:
            self.store.dead_letter(operation["id"], "ACTION_NOT_SUPPORTED", checkpoint, iso(current_time))
            return {"operation_id": operation["id"], "outcome": "dead-letter"}
        try:
            self.save(operation["id"], "RUNNING", "provider.instance.create", checkpoint, current_time)
            completed = provisioner.provision(operation["id"], operation["request"], checkpoint)
            self.save(operation["id"], "SUCCEEDED", "complete", completed, current_time, release=True)
            return {"operation_id": operation["id"], "outcome": "succeeded", "checkpoint": completed}
        except ProviderError as exc:
            checkpoint = getattr(exc, "checkpoint", checkpoint)
            if exc.retryable and operation["attempt"] < self.max_attempts:
                delay = min(300, 2 ** (operation["attempt"] - 1))
                self.save(operation["id"], "RUNNING", "provider.retry", checkpoint, current_time, retry_after=delay, release=True)
                return {"operation_id": operation["id"], "outcome": "retry", "retry_after": delay}
            provisioner.compensate(checkpoint)
            self.store.dead_letter(operation["id"], exc.code, checkpoint, iso(current_time))
            return {"operation_id": operation["id"], "outcome": "dead-letter"}
