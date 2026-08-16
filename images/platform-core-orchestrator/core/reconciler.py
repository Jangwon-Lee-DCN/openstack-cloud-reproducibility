import uuid
from datetime import datetime, timezone


class AutoScalingReconciler:
    """Persisted desired/actual reconciler against a compute adapter contract."""

    def __init__(self, store, compute): self.store, self.compute = store, compute

    def reconcile_one(self, group_id):
        with self.store.tx() as db:
            group = db.execute("SELECT * FROM auto_scaling_groups WHERE id=?", (group_id,)).fetchone()
            if not group: return None
            members = list(db.execute("SELECT * FROM asg_members WHERE group_id=? ORDER BY created_at,id", (group_id,)))
            desired = group["desired"]
        if len(members) < desired:
            for sequence in range(len(members), desired):
                provider_id = self.compute.create_server(f"asg-{group_id}-{sequence}", {"group_id": group_id})
                with self.store.tx() as db:
                    db.execute("INSERT OR IGNORE INTO asg_members VALUES(?,?,?,?,?)", (str(uuid.uuid4()), group_id, provider_id, "ACTIVE", datetime.now(timezone.utc).isoformat()))
        elif len(members) > desired:
            for member in reversed(members[desired:]):
                with self.store.tx() as db:
                    protected = db.execute("SELECT protected FROM resource_protection WHERE project_id=? AND resource_type='instance' AND resource_id=?", (group["project_id"], member["provider_id"])).fetchone()
                    if protected and protected[0]:
                        db.execute("UPDATE auto_scaling_groups SET state='DEGRADED' WHERE id=?", (group_id,)); continue
                self.compute.delete_server(member["provider_id"])
                with self.store.tx() as db: db.execute("DELETE FROM asg_members WHERE id=?", (member["id"],))
        with self.store.tx() as db:
            count = db.execute("SELECT COUNT(*) FROM asg_members WHERE group_id=?", (group_id,)).fetchone()[0]
            if count == desired: db.execute("UPDATE auto_scaling_groups SET state='ACTIVE' WHERE id=?", (group_id,))
            return {"group_id": group_id, "desired": desired, "actual": count}

    def reconcile_all(self):
        with self.store.tx() as db: ids = [row[0] for row in db.execute("SELECT id FROM auto_scaling_groups WHERE state IN ('SCALING','DEGRADED')")]
        return [self.reconcile_one(ident) for ident in ids]
