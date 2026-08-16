import json
import uuid
from datetime import datetime, timedelta, timezone

from .adapters import ProviderError
from .store import Store


def now(): return datetime.now(timezone.utc).isoformat()


class ASGResourceProvider:
    def __init__(self, provisioner): self.provisioner = provisioner
    def provision_member(self, operation_id, spec, checkpoint, callback):
        return self.provisioner.provision(operation_id, spec, checkpoint, callback)
    def delete_member(self, checkpoint): self.provisioner.compensate(checkpoint)


class AutoScalingReconciler:
    """Durable desired/actual reconciler for a complete member resource-set."""
    def __init__(self, store, provider, max_attempts=5):
        self.store, self.provider, self.max_attempts = store, provider, max_attempts

    def _spec(self, db, group):
        row = db.execute("SELECT spec_json FROM launch_template_versions WHERE template_id=? AND version=?",
                         (group["template_id"], group["template_version"])).fetchone()
        spec = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        subnet_ids = group["subnet_ids"] or []
        subnet_id = spec.get("subnet_id") or (subnet_ids[0] if subnet_ids else None)
        network = {"subnet_id": subnet_id, "network_id": spec.get("network_id"),
                   "security_group_ids": spec.get("security_group_ids")}
        network = {key: value for key, value in network.items() if value is not None}
        result = {"network": network, "server": {"image_id": spec["image_id"], "flavor_id": spec["flavor_id"]}}
        if spec.get("volume_size_gib"):
            result["volume"] = {"size_gib": spec["volume_size_gib"], "volume_type": spec.get("volume_type"),
                                "image_id": spec["image_id"]}
        return result

    def _checkpoint(self, member_id, checkpoint):
        with self.store.tx() as db:
            db.execute("UPDATE asg_members SET resource_set_json=?,provider_id=?,updated_at=? WHERE id=?",
                       (json.dumps(checkpoint, sort_keys=True), checkpoint.get("server_id"), now(), member_id))

    def _reserve(self, group_id):
        member_id, timestamp = str(uuid.uuid4()), now()
        with self.store.tx() as db:
            db.execute("INSERT INTO asg_members(id,group_id,provider_id,state,created_at,operation_id,resource_set_json,updated_at,retry_count,next_retry_at,error_code) "
                       "VALUES(?,?,NULL,'CREATING',?,?,?,?,0,NULL,NULL)",
                       (member_id, group_id, timestamp, member_id, "{}", timestamp))
        return member_id

    def _create(self, group, member):
        checkpoint = member.get("resource_set") or {}
        try:
            with self.store.tx() as db: spec = self._spec(db, group)
            completed = self.provider.provision_member(str(member["operation_id"]), spec, checkpoint,
                                                        lambda value: self._checkpoint(str(member["id"]), value))
            with self.store.tx() as db:
                db.execute("UPDATE asg_members SET provider_id=?,state='ACTIVE',resource_set_json=?,updated_at=?,next_retry_at=NULL,error_code=NULL WHERE id=?",
                           (completed["server_id"], json.dumps(completed, sort_keys=True), now(), member["id"]))
            return True
        except ProviderError as exc:
            retry_count = int(member.get("retry_count") or 0) + 1
            retryable = exc.retryable and retry_count < self.max_attempts
            delay = min(300, 2 ** (retry_count - 1))
            with self.store.tx() as db:
                db.execute("UPDATE asg_members SET state=?,retry_count=?,next_retry_at=?,error_code=?,updated_at=? WHERE id=?",
                           ("CREATING" if retryable else "FAILED", retry_count,
                            (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat() if retryable else None,
                            exc.code, now(), member["id"]))
                db.execute("UPDATE auto_scaling_groups SET state=? WHERE id=?", ("SCALING" if retryable else "DEGRADED", group["id"]))
            return False

    def _delete(self, group, member):
        with self.store.tx() as db:
            protected = db.execute("SELECT protected FROM resource_protection WHERE project_id=? AND resource_type='instance' AND resource_id=?",
                                   (group["project_id"], member["provider_id"])).fetchone()
            if protected and protected[0]:
                db.execute("UPDATE auto_scaling_groups SET state='DEGRADED' WHERE id=?", (group["id"],)); return False
            db.execute("UPDATE asg_members SET state='DELETING',updated_at=? WHERE id=?", (now(), member["id"]))
        try:
            self.provider.delete_member(member.get("resource_set") or {})
            with self.store.tx() as db: db.execute("DELETE FROM asg_members WHERE id=?", (member["id"],))
            return True
        except ProviderError as exc:
            with self.store.tx() as db:
                db.execute("UPDATE asg_members SET error_code=?,retry_count=retry_count+1,updated_at=? WHERE id=?",
                           (exc.code, now(), member["id"]))
                db.execute("UPDATE auto_scaling_groups SET state='DEGRADED' WHERE id=?", (group["id"],))
            return False

    def reconcile_one(self, group_id):
        with self.store.tx() as db:
            raw = db.execute("SELECT * FROM auto_scaling_groups WHERE id=?", (group_id,)).fetchone()
            if not raw: return None
            group = Store.row(raw); desired = group["desired"]
            members = [Store.row(row) for row in db.execute("SELECT * FROM asg_members WHERE group_id=? ORDER BY created_at,id", (group_id,))]
        for member in [item for item in members if item["state"] == "DELETING"]: self._delete(group, member)
        members = [item for item in members if item["state"] != "DELETING"]
        live = [item for item in members if item["state"] in {"CREATING", "ACTIVE"}]
        has_failed = any(item["state"] == "FAILED" for item in members)
        while len(live) < desired and not has_failed:
            member_id = self._reserve(group_id)
            with self.store.tx() as db: member = Store.row(db.execute("SELECT * FROM asg_members WHERE id=?", (member_id,)).fetchone())
            self._create(group, member); live.append(member)
        with self.store.tx() as db:
            live = [Store.row(row) for row in db.execute(
                "SELECT * FROM asg_members WHERE group_id=? AND state IN ('CREATING','ACTIVE') ORDER BY created_at,id", (group_id,))]
        current_time = now()
        for member in [item for item in live if item["state"] == "CREATING" and (not item.get("next_retry_at") or item["next_retry_at"] <= current_time)]:
            self._create(group, member)
        with self.store.tx() as db:
            members = [Store.row(row) for row in db.execute("SELECT * FROM asg_members WHERE group_id=? ORDER BY created_at,id", (group_id,))]
        active = [item for item in members if item["state"] == "ACTIVE"]
        for member in reversed(active[desired:]): self._delete(group, member)
        with self.store.tx() as db:
            rows = [Store.row(row) for row in db.execute("SELECT * FROM asg_members WHERE group_id=?", (group_id,))]
            active_count = len([item for item in rows if item["state"] == "ACTIVE"])
            pending = any(item["state"] in {"CREATING", "DELETING"} for item in rows)
            failed = any(item["state"] == "FAILED" for item in rows)
            state = "DEGRADED" if failed or active_count > desired else ("SCALING" if pending or active_count != desired else "ACTIVE")
            db.execute("UPDATE auto_scaling_groups SET state=? WHERE id=?", (state, group_id))
            return {"group_id": str(group_id), "desired": desired, "actual": active_count, "state": state}

    def reconcile_all(self):
        with self.store.tx() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM auto_scaling_groups WHERE state IN ('SCALING','DEGRADED')")]
        return [self.reconcile_one(ident) for ident in ids]
