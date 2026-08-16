from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .workflows import WorkflowError


class NativeTagAdapter(Protocol):
    service: str

    def read(self, resource_id: str) -> dict[str, str]: ...
    def write(self, resource_id: str, tags: dict[str, str], expected_revision: int) -> int: ...


@dataclass
class FakeNativeTagAdapter:
    service: str
    resources: dict[str, tuple[int, dict[str, str]]] = field(default_factory=dict)

    def read(self, resource_id: str) -> dict[str, str]:
        if resource_id not in self.resources:
            raise WorkflowError("native resource not found")
        return dict(self.resources[resource_id][1])

    def revision(self, resource_id: str) -> int:
        return self.resources[resource_id][0]

    def write(self, resource_id: str, tags: dict[str, str], expected_revision: int) -> int:
        revision, _ = self.resources.get(resource_id, (0, {}))
        if revision != expected_revision:
            raise WorkflowError("native tag revision conflict")
        revision += 1
        self.resources[resource_id] = (revision, dict(tags))
        return revision


@dataclass(frozen=True)
class DriftResult:
    resource_id: str
    changed: bool
    before: dict[str, str]
    after: dict[str, str]
    revision: int


class TagReconciler:
    def reconcile(self, adapter: FakeNativeTagAdapter, resource_id: str,
                  desired: dict[str, str], *, dry_run=False) -> DriftResult:
        before = adapter.read(resource_id)
        merged = dict(before)
        for key, value in desired.items():
            if key.startswith("dcn.ssu.ac.kr/") or key.startswith("system/"):
                merged[key] = value
            elif key not in before:
                merged[key] = value
        changed = merged != before
        revision = adapter.revision(resource_id)
        if changed and not dry_run:
            revision = adapter.write(resource_id, merged, revision)
        return DriftResult(resource_id, changed, before, merged, revision)
