from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    mode: str
    database: str

    @classmethod
    def from_env(cls) -> "Config":
        mode = os.environ.get("RESILIENCE_MODE", "development")
        if mode not in {"development", "production"}:
            raise RuntimeError("RESILIENCE_MODE must be development or production")
        if mode == "production":
            required = ("KEYSTONE_AUTH_URL", "OPA_URL", "TRACK_A_URL", "TRACK_B_URL", "OPENSTACK_ADAPTER_SET")
            missing = [name for name in required if not os.environ.get(name)]
            if missing:
                raise RuntimeError(f"production integration is fail-closed; missing {missing}")
            # Real client implementations are intentionally outside this branch.
            raise RuntimeError("production mode unavailable until real integration clients are installed")
        return cls(mode=mode, database=os.environ.get("RESILIENCE_DB", "/data/resilience.db"))
